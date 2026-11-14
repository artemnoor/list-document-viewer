"""Live registration/login/logout smoke check. Creates one uniquely named test account."""
import argparse
import http.cookiejar
import json
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    base = parser.parse_args().base_url.rstrip("/")
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    checks = 0

    def request(path, method="GET", body=None, expected=200, origin=None):
        nonlocal checks
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers, method=method)
        try:
            response = client.open(req, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        assert response.status == expected, (path, response.status, expected)
        data = response.read()
        checks += 1
        return json.loads(data) if data else None

    credentials = {"email": f"account-smoke-{uuid.uuid4().hex}@example.test", "password": "1"}
    request("/api/auth/me", expected=401)
    registered = request("/api/auth/register", "POST", credentials, 201)
    assert registered["user"]["email"] == credentials["email"]
    assert any(cookie.name == "trace_session" and cookie.has_nonstandard_attr("HttpOnly") for cookie in jar)
    assert request("/api/auth/me")["user"]["id"] == registered["user"]["id"]
    request("/api/auth/register", "POST", {**credentials, "email": credentials["email"].upper()}, 409)
    request("/api/auth/logout", "POST", expected=204)
    request("/api/auth/me", expected=401)
    request("/api/auth/login", "POST", {**credentials, "password": "wrong"}, 401)
    request("/api/auth/login", "POST", {**credentials, "email": "  " + credentials["email"].upper() + "  "})
    assert request("/api/auth/me")["user"]["id"] == registered["user"]["id"]
    request("/api/auth/logout", "POST", expected=403, origin="https://other.example")
    assert request("/api/auth/me")["user"]["id"] == registered["user"]["id"]
    request("/api/auth/logout", "POST", expected=204)
    request("/api/auth/me", expected=401)
    print(f"Passed {checks} live account checks; one-character password accepted; session revoked on logout.")


if __name__ == "__main__":
    main()
