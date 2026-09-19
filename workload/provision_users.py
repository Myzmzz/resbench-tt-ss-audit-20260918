"""在集群内为压测建合成账号（通过业务接口写测试数据，不改系统）。

由一次性 Job 运行；账号口令只从 Secret 注入的环境变量读取，本脚本只打印每一步的状态码，
不打印任何口令、令牌或会话。所有资料都是明显的合成值（测试卡号 4111...1111）。

环境变量：SYSTEM=train-ticket|sock-shop，BASE_URL，WL_USERNAME，WL_PASSWORD
"""
import base64
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request

SYSTEM, BASE = os.environ["SYSTEM"], os.environ["BASE_URL"].rstrip("/")
USER, PASSWORD = os.environ["WL_USERNAME"], os.environ["WL_PASSWORD"]
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(step, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with opener.open(req, timeout=30) as resp:
            code, raw = resp.status, resp.read()
    except urllib.error.HTTPError as err:
        code, raw = err.code, err.read()
    except Exception as err:  # 连接失败等
        print(json.dumps({"step": step, "status": "error", "error": type(err).__name__}), flush=True)
        return None, None
    print(json.dumps({"step": step, "status": code}), flush=True)
    try:
        return code, json.loads(raw or b"null")
    except ValueError:
        return code, None


if SYSTEM == "train-ticket":
    call("register", "POST", "/api/v1/userservice/users/register",
         {"userName": USER, "password": PASSWORD, "gender": 1, "documentType": 1,
          "documentNum": "ID-AUDIT-0001", "email": "resbench-audit@example.invalid"})
    code, payload = call("login", "POST", "/api/v1/users/login",
                         {"username": USER, "password": PASSWORD, "verificationCode": ""})
    data = (payload or {}).get("data") or {}
    token, account = data.get("token"), data.get("userId")
    if not token or not account:
        print(json.dumps({"step": "login", "result": "no-token"}), flush=True)
        sys.exit(1)
    auth = {"Authorization": "Bearer " + token}
    code, payload = call("list-contacts", "GET", f"/api/v1/contactservice/contacts/account/{account}", headers=auth)
    existing = (payload or {}).get("data") or []
    if not existing:
        call("create-contact", "POST", "/api/v1/contactservice/contacts",
             {"accountId": account, "name": "Audit Contact", "documentType": 1,
              "documentNumber": "DOC-AUDIT-0001", "phoneNumber": "13800000000"}, headers=auth)
    code, payload = call("verify-contacts", "GET", f"/api/v1/contactservice/contacts/account/{account}", headers=auth)
    print(json.dumps({"result": "contacts", "count": len((payload or {}).get("data") or [])}), flush=True)
elif SYSTEM == "sock-shop":
    # 注意：front-end 的 GET /addresses、GET /cards 返回全站数据、不按用户过滤（数据隔离问题），
    # 所以必须按客户查：先从 /customers/<任意> 拿到当前会话的客户编号，再直接问 user 服务该客户名下的地址与卡。
    USER_SVC = os.environ.get("USER_SVC", "http://user").rstrip("/")
    call("register", "POST", "/register",
         {"username": USER, "password": PASSWORD, "email": "resbench-audit@example.invalid",
          "firstName": "Resbench", "lastName": "Audit"})
    basic = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    call("login", "GET", "/login", headers={"Authorization": "Basic " + basic})
    code, me = call("current-customer", "GET", "/customers/me")
    cust = (me or {}).get("id")
    if not cust:
        print(json.dumps({"step": "current-customer", "result": "no-id"}), flush=True)
        sys.exit(1)

    def linked(kind):
        req = urllib.request.Request(f"{USER_SVC}/customers/{cust}/{kind}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read() or b"null") or {}
        except urllib.error.HTTPError as err:
            print(json.dumps({"step": f"linked-{kind}", "status": err.code}), flush=True)
            return 0
        return len((body.get("_embedded") or {}).get("address" if kind == "addresses" else "card") or [])

    if linked("addresses") == 0:
        call("add-address", "POST", "/addresses",
             {"street": "Audit Street", "number": "1", "country": "CN", "city": "Hangzhou", "postcode": "310000"})
    if linked("cards") == 0:
        call("add-card", "POST", "/cards", {"longNum": "4111111111111111", "expires": "12/30", "ccv": "123"})
    print(json.dumps({"result": "linked-to-customer", "addresses": linked("addresses"), "cards": linked("cards")}), flush=True)
else:
    sys.exit("unknown SYSTEM")
