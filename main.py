from typing import Annotated, Union
from fastapi import FastAPI, Response, Cookie, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse 
from starlette.middleware.sessions import SessionMiddleware
import os
from stream_unzip import async_stream_unzip
import httpx
from cachetools import TTLCache
import secrets

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
GITHUB_USER = os.getenv("GITHUB_USER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
FILENAME = os.getenv("FILENAME")
SECRET_KEY = os.getenv("SECRET_KEY")

CHUNK_SIZE = 64 * 1024 # 64KB

app = FastAPI(
    #    title="Vercel + FastAPI",
    #    description="Vercel + FastAPI",
    #    version="1.0.0",
)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

sessions = TTLCache(maxsize=5, ttl=3600)

async def get_httpx_async_client():
    async with httpx.AsyncClient() as client:
        yield client

HttpxClientDep = Annotated[httpx.AsyncClient, Depends(get_httpx_async_client)]

class PdfStreamingResponse(StreamingResponse):
    media_type = "application/pdf"

@app.get("/", response_class=Union[HTMLResponse, PdfStreamingResponse])
async def index(httpx_client: HttpxClientDep, request: Request):
    session_id = request.session.get('session_id')
    if session_id is None or sessions.get(session_id) is None:

        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
        <meta charset="utf-8"> 
        </head>
        <body>
            <a href="https://github.com/login/oauth/authorize?client_id={CLIENT_ID}&scope=repo">Login with GitHub</a>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content, status_code=200)

    else:

        token = sessions[session_id]

        headers = {"Accept": "application/vnd.github+json",
                   "Authorization": f"Bearer {token}",
                   "X-GitHub-Api-Version": "2022-11-28"
                   }
        url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/actions/artifacts"

        r = await httpx_client.get(url, headers=headers)
        if r.status_code != 200:
            raise HTTPException(502, detail="Could not get artifacts") # Bad Gateway
        artifacts_response = r.json()
        artifacts = artifacts_response["artifacts"]
        valid_artifacts = [artifact for artifact in artifacts if artifact["expired"] is False]
        if not valid_artifacts:
            raise HTTPException(status_code=404, detail="No artifacts found")

        latest_artifact = max(valid_artifacts, key=lambda artifact: artifact["updated_at"])
        artifact_url = latest_artifact["archive_download_url"]

        async def pdf_stream(): 
            async with httpx_client.stream('GET', artifact_url, headers=headers, follow_redirects=True) as artifact_stream_response:
                async for file_name, file_size, unzipped_chunks in async_stream_unzip(artifact_stream_response.aiter_bytes(chunk_size=CHUNK_SIZE), chunk_size=CHUNK_SIZE):
                    if file_name.decode("utf-8") == FILENAME:
                        async for chunk in unzipped_chunks:
                            yield chunk
                        return
            
            raise HTTPException(404, "file could not be found")

        return PdfStreamingResponse(pdf_stream())


@app.get("/github/callback")
async def github_callback(code: str, httpx_client: HttpxClientDep, request: Request):

    if not code:
        raise HTTPException(400, detail="code must be provided") # Bad Request

    token_data = await exchange_code(code, httpx_client)
    token = token_data.get("access_token")
    if not token:
        raise HTTPException(502, detail="access token missing") # Bad Gateway

    session_id = secrets.token_urlsafe()
    sessions[session_id] = token

    redirect = RedirectResponse("/")
    request.session['session_id'] = session_id

    return redirect


async def exchange_code(code, httpx_client: HttpxClientDep):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
    }
    headers = {"accept": "application/json"}

    r = await httpx_client.post("https://github.com/login/oauth/access_token", headers=headers, data=data)

    if r.status_code != 200:
        raise HTTPException(502, detail="Could not exchange code for access token") # Bad Gateway


    return r.json()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
