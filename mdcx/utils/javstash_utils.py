import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

STASH_ME_QUERY = "query Me { me { name } }"
STASH_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
}

def parse_javstash_response(res_data: dict | None, error: str | None = None, status_code: int | None = None) -> tuple[bool, str]:
    """
    Unified parser for Stash-Box GraphQL responses.
    Returns (success, tip_message).
    """
    if error:
        return False, f"❌ JavStash 连接失败: {error}"
        
    if status_code in [401, 403]:
        return False, "❌ API Key 无效或无权限！请到「设置」-「网络」中修改。"
        
    if status_code and status_code != 200:
        return False, f"❌ 连接失败！HTTP {status_code}"

    if res_data:
        # Some clients return the 'data' wrapper, some return the inner body
        data = res_data.get("data") if isinstance(res_data, dict) and "data" in res_data else res_data
        
        if isinstance(res_data, dict) and "errors" in res_data:
            error_msg = res_data["errors"][0].get("message", "未知错误")
            return False, f"❌ JavStash 密钥无效或请求出错！({error_msg})"
            
        if isinstance(data, dict):
            user_name = data.get("me", {}).get("name", "Unknown")
            return True, f"✅ 连接正常！欢迎，{user_name}"

    return False, "❌ 返回数据异常！"

def verify_javstash_connection_sync(url: str, api_key: str, proxy: str | None = None, timeout: int = 5) -> tuple[bool, str]:
    """
    Synchronously verify connection to a Stash-Box instance.
    Used by configuration validators and UI test buttons.
    """
    if not url or not api_key:
        return False, "❌ 未填写 URL 或 API Key"
        
    endpoint = f"{url.rstrip('/')}/graphql"
    try:
        data = json.dumps({"query": STASH_ME_QUERY}).encode("utf-8")
        headers = {**STASH_HEADERS, "ApiKey": api_key}
        
        # Configure proxy if provided
        if proxy:
            proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
            opener = urllib.request.build_opener(proxy_handler)
        else:
            opener = urllib.request.build_opener()
            
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        with opener.open(req, timeout=timeout) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return parse_javstash_response(res_data, status_code=response.status)
            
    except urllib.error.HTTPError as e:
        return parse_javstash_response(None, status_code=e.code)
    except Exception as e:
        logger.warning("JavStash connection check failed for %s: %s", url, e)
        return parse_javstash_response(None, error=str(e))
