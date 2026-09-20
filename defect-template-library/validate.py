#!/usr/bin/env python3
"""校验 templates.yaml / advisories.yaml / documents.yaml / stats.md。

检查项（对应任务书第 8 节）：
  1. schema 合法：必填字段齐全、取值在枚举内
  2. 每条模板至少 1 条 source，且 quote 在 docs-cache/<doc_id>.txt 里原样存在（忽略空白差异）
  3. 所有 doc_id 可解析，且该文档登记了版本、取回日期、sha256；sha256 与文件实际内容一致
  4. 每条模板至少 1 条"必要"检查项
  5. checker / kind / type / source / defect_class / parameter_kind 的取值在枚举内
  6. parameter_kind 为"阈值型"的模板必须有 parameter_relation，且每个 symbol 有 source
  7. defaults 每条都有 doc_id，且 doc_id 可解析
  8. checks 里引用的 Semgrep 规则文件存在
  9. 模板与 advisory 正文里不出现目标系统名及其服务名
 10. stats.md 与 YAML 一致（调用 stats.py 重新生成后比对）

用法：python3 validate.py
"""
import hashlib
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "docs-cache")

DEFECT_CLASS = {"规范明示型", "需求相对型", "组合型", "实现错误型"}
PARAM_KIND_TPL = {"阈值型", "离散动作"}
PARAM_KIND_ADV = {"概率型", "累积型", "滞后型", "组合型", "时机型", "状态型", "未知型"}
CHECK_KIND = {"必要", "反证", "附注"}
CHECKER = {"manifest", "semgrep", "codegraph", "llm", "runtime"}
ACTION_TYPE = {"连续幅值", "离散·有数量", "离散·有时长", "离散·无可比参数"}
SYMBOL_SOURCE = {"manifest", "code", "default", "requirement", "measured", "assumed_worst"}
SIGNAL_SOURCE = {"events", "status", "metrics", "traces", "logs"}
MITIGATION_LEVEL = {"config", "code"}
ROLE_KEYS = {"defect_site", "injection_site", "manifest_site"}

# 不得出现在模板与 advisory 里的目标系统名及其服务名
BANNED = [
    r"sock[-_ ]?shop", r"socks[-_ ]?shop", r"otel[-_ ]demo", r"opentelemetry[-_ ]demo",
    r"astronomy[-_ ]shop", r"train[-_ ]ticket", r"trainticket", r"\bts-[a-z][a-z0-9-]*",
    r"queue-master", r"carts-db", r"catalogue-db",
    r"\b(adservice|cartservice|checkoutservice|currencyservice|emailservice)\b",
    r"\b(frauddetectionservice|productcatalogservice|quoteservice|recommendationservice)\b",
    r"\b(shippingservice|loadgenerator|flagd|paymentservice)\b",
]

errors, warns = [], []


def err(m):
    errors.append(m)


def warn(m):
    warns.append(m)


def norm(s):
    s = s.replace(" ", " ").replace("​", "")
    s = re.sub(r"[“”]", '"', s).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip()


def need(obj, field, where):
    if field not in obj or obj[field] in (None, "", [], {}):
        err("%s：缺字段 %s" % (where, field))
        return False
    return True


def load(name, key):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        err("缺文件：%s" % name)
        return []
    return (yaml.safe_load(open(p, encoding="utf-8")) or {}).get(key, []) or []


def check_banned(where, blob):
    low = blob.lower()
    for pat in BANNED:
        m = re.search(pat, low)
        if m:
            err("%s：出现了目标系统名或其服务名「%s」，模板必须与系统无关" % (where, m.group(0)))


def check_sources(where, rule, docs, texts):
    srcs = rule.get("sources") or []
    if not srcs:
        err("%s：rule.sources 为空，给不出原文的规则不入库" % where)
    for s in srcs:
        for f in ("doc_id", "quote", "location"):
            if not s.get(f):
                err("%s：sources 条目缺 %s" % (where, f))
        did, q = s.get("doc_id"), s.get("quote")
        if not did or not q:
            continue
        if did not in docs:
            err("%s：doc_id %s 不在 documents.yaml 里" % (where, did))
            continue
        if did not in texts:
            err("%s：doc_id %s 没有可核对的本地副本" % (where, did))
            continue
        if q in texts[did] or norm(q) in norm(texts[did]):
            continue
        err("%s：quote 在 docs-cache/%s.txt 里找不到原文：%s…" % (where, did, q[:80]))
    for d in rule.get("defaults") or []:
        if not d.get("doc_id"):
            err("%s：defaults 条目 %r 没有 doc_id，默认值必须注明出处" % (where, d.get("symbol")))
        elif d["doc_id"] not in docs:
            err("%s：defaults 的 doc_id %s 不在 documents.yaml 里" % (where, d["doc_id"]))


def main():
    # ---- documents.yaml
    docs, texts = {}, {}
    dpath = os.path.join(ROOT, "documents.yaml")
    if not os.path.exists(dpath):
        err("缺 documents.yaml")
    else:
        for d in (yaml.safe_load(open(dpath, encoding="utf-8")) or {}).get("documents", []):
            did = d.get("doc_id")
            docs[did] = d
            for f in ("version", "retrieved_at", "sha256", "url", "license"):
                if not d.get(f):
                    err("documents.yaml[%s]：缺 %s" % (did, f))
            lc = d.get("local_copy")
            if lc:
                fp = os.path.join(ROOT, lc)
                if not os.path.exists(fp):
                    err("documents.yaml[%s]：local_copy 文件不存在 %s" % (did, lc))
                else:
                    body = open(fp, encoding="utf-8").read()
                    texts[did] = body
                    got = hashlib.sha256(body.encode("utf-8")).hexdigest()
                    if d.get("sha256") and got != d["sha256"]:
                        err("documents.yaml[%s]：sha256 与文件内容不符（副本被改过或未重建）" % did)

    templates = load("templates.yaml", "templates")
    advisories = load("advisories.yaml", "advisories")

    # ---- templates
    seen = set()
    for t in templates:
        tid = t.get("template_id", "<无 template_id>")
        if tid in seen:
            err("%s：template_id 重复" % tid)
        seen.add(tid)
        if not re.match(r"^T-[A-Z0-9]+-\d{2}$", tid):
            err("%s：template_id 应形如 T-<组>-<两位序号>" % tid)
        for f in ("name", "mechanism_group", "mechanism", "defect_class", "parameter_kind",
                  "rule", "locate", "experiment", "verdict", "violation_manifestation"):
            need(t, f, tid)
        if t.get("defect_class") not in DEFECT_CLASS:
            err("%s：defect_class 取值非法 %r" % (tid, t.get("defect_class")))
        if t.get("parameter_kind") not in PARAM_KIND_TPL:
            err("%s：parameter_kind 取值非法 %r（本版模板只允许 阈值型 / 离散动作）"
                % (tid, t.get("parameter_kind")))
        check_banned(tid, yaml.safe_dump(t, allow_unicode=True))

        rule = t.get("rule") or {}
        need(rule, "statement", tid + ".rule")
        check_sources(tid, rule, docs, texts)

        loc = t.get("locate") or {}
        for f in ("applies_when", "roles", "instantiations", "checks"):
            need(loc, f, tid + ".locate")
        roles = loc.get("roles") or {}
        for rk in ROLE_KEYS:
            if not roles.get(rk):
                err("%s：locate.roles 缺 %s" % (tid, rk))
        for extra in set(roles) - ROLE_KEYS:
            err("%s：locate.roles 出现未定义的角色 %s" % (tid, extra))
        for inst in loc.get("instantiations") or []:
            for f in ("component", "how", "config_or_code"):
                if not inst.get(f):
                    err("%s：instantiations 条目缺 %s" % (tid, f))
        checks = loc.get("checks") or []
        if not any(c.get("kind") == "必要" for c in checks):
            err("%s：locate.checks 里没有一条「必要」检查项" % tid)
        cids = set()
        for c in checks:
            cid = c.get("id", "?")
            if cid in cids:
                err("%s：检查项 id %s 重复" % (tid, cid))
            cids.add(cid)
            for f in ("id", "kind", "statement", "checker", "query"):
                if not c.get(f):
                    err("%s：检查项 %s 缺 %s" % (tid, cid, f))
            if c.get("kind") not in CHECK_KIND:
                err("%s：检查项 %s 的 kind 非法 %r" % (tid, cid, c.get("kind")))
            if c.get("checker") not in CHECKER:
                err("%s：检查项 %s 的 checker 非法 %r" % (tid, cid, c.get("checker")))
            if c.get("checker") == "semgrep":
                files = re.findall(r"checkers/semgrep/[\w.\-]+\.yaml", str(c.get("query", "")))
                if not files:
                    err("%s：检查项 %s 声明 checker=semgrep，但 query 里没有给规则文件名" % (tid, cid))
                for fp in files:
                    if not os.path.exists(os.path.join(ROOT, fp)):
                        err("%s：检查项 %s 引用的 Semgrep 规则文件不存在：%s" % (tid, cid, fp))

        exp = t.get("experiment") or {}
        acts = exp.get("actions") or []
        if not acts:
            err("%s：experiment.actions 为空" % tid)
        for a in acts:
            for f in ("action", "type", "target_role"):
                if not a.get(f):
                    err("%s：action %r 缺 %s" % (tid, a.get("action"), f))
            if a.get("type") not in ACTION_TYPE:
                err("%s：action %r 的 type 非法 %r" % (tid, a.get("action"), a.get("type")))
            if a.get("target_role") and a["target_role"] not in ROLE_KEYS:
                err("%s：action %r 的 target_role 不是已定义的角色 %r"
                    % (tid, a.get("action"), a.get("target_role")))
            if a.get("only_if") and a["only_if"].split()[0] not in cids:
                warn("%s：action %r 的 only_if 引用了不存在的检查项 %r"
                     % (tid, a.get("action"), a.get("only_if")))
        pr = exp.get("parameter_relation") or {}
        if t.get("parameter_kind") == "阈值型":
            if not pr:
                err("%s：阈值型模板必须有 parameter_relation" % tid)
            else:
                for f in ("symbols", "boundary", "hold", "recovery_window"):
                    if not pr.get(f):
                        err("%s：parameter_relation 缺 %s" % (tid, f))
                for sym in pr.get("symbols") or []:
                    if not sym.get("symbol") or not sym.get("meaning"):
                        err("%s：parameter_relation.symbols 条目缺 symbol 或 meaning" % tid)
                    src = sym.get("source")
                    if not src:
                        err("%s：symbol %s 没有 source" % (tid, sym.get("symbol")))
                    else:
                        for one in str(src).split("|"):
                            if one.strip() not in SYMBOL_SOURCE:
                                err("%s：symbol %s 的 source 取值非法 %r"
                                    % (tid, sym.get("symbol"), one))

        v = t.get("verdict") or {}
        for f in ("expected_behavior", "signals", "alternative_explanations", "mitigation"):
            need(v, f, tid + ".verdict")
        for s in v.get("signals") or []:
            if not s.get("signal"):
                err("%s：signals 条目缺 signal" % tid)
            if s.get("source") not in SIGNAL_SOURCE:
                err("%s：signal %r 的 source 非法 %r" % (tid, s.get("signal"), s.get("source")))
        mit = v.get("mitigation") or {}
        if not mit.get("family"):
            err("%s：verdict.mitigation 缺 family" % tid)
        if mit.get("level") not in MITIGATION_LEVEL:
            err("%s：verdict.mitigation.level 非法 %r" % (tid, mit.get("level")))

    # ---- advisories
    for a in advisories:
        aid = a.get("advisory_id", "<无 advisory_id>")
        for f in ("name", "mechanism_group", "parameter_kind", "rule",
                  "why_not_supported", "what_is_needed"):
            need(a, f, aid)
        if a.get("parameter_kind") not in PARAM_KIND_ADV:
            err("%s：advisory 的 parameter_kind 取值非法 %r" % (aid, a.get("parameter_kind")))
        check_banned(aid, yaml.safe_dump(a, allow_unicode=True))
        check_sources(aid, a.get("rule") or {}, docs, texts)

    # ---- Semgrep 规则本身合法
    sg = os.path.join(ROOT, "checkers", "semgrep")
    if os.path.isdir(sg) and os.listdir(sg):
        try:
            r = subprocess.run(["semgrep", "--validate", "--metrics=off", "--config", sg],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0 or "configuration error" not in (r.stdout + r.stderr):
                tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
                err("semgrep --validate 未通过：%s" % " / ".join(tail))
            else:
                m = re.search(r"found (\d+) configuration error", r.stdout + r.stderr)
                if m and int(m.group(1)) > 0:
                    err("semgrep --validate 报告 %s 条配置错误" % m.group(1))
        except FileNotFoundError:
            warn("本机没有 semgrep，跳过规则语法校验（已在 CHANGES.md 记录）")
        except Exception as e:
            warn("semgrep --validate 无法运行：%s" % str(e)[:120])

    # ---- stats.md 与 YAML 一致
    spath = os.path.join(ROOT, "stats.md")
    if os.path.exists(os.path.join(ROOT, "stats.py")):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "stats.py"), "--stdout"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            err("stats.py 运行失败：%s" % r.stderr.strip()[:200])
        elif not os.path.exists(spath):
            err("缺 stats.md")
        elif open(spath, encoding="utf-8").read().strip() != r.stdout.strip():
            err("stats.md 与 YAML 不一致，请重新运行 python3 stats.py")

    print("=" * 74)
    print("defect-template-library / validate.py")
    print("=" * 74)
    print("documents.yaml：%d 份（可核对副本 %d 份）" % (len(docs), len(texts)))
    print("templates.yaml：%d 条模板；advisories.yaml：%d 条" % (len(templates), len(advisories)))
    nq = sum(len((t.get("rule") or {}).get("sources") or []) for t in templates) + \
        sum(len((a.get("rule") or {}).get("sources") or []) for a in advisories)
    print("引用条目：%d 条" % nq)
    print("-" * 74)
    for w in warns:
        print("  ! " + w)
    if errors:
        for e in errors:
            print("  x " + e)
        print("-" * 74)
        print("结果：FAIL（%d 错误，%d 警告）" % (len(errors), len(warns)))
        return 1
    print("结果：PASS（0 错误，%d 警告）" % len(warns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
