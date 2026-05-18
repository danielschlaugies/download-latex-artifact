import io
from typing import Annotated
from fastapi import FastAPI, Response, Cookie, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse 
import os
import zipfile
import requests
from cachetools import TTLCache
import uuid

app = FastAPI(
    #    title="Vercel + FastAPI",
    #    description="Vercel + FastAPI",
    #    version="1.0.0",
)

sessions = TTLCache(maxsize=5, ttl=3600)

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")


@app.get("/")
async def index(session_id: Annotated[uuid.UUID | None, Cookie()] = None):
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
        url = "https://api.github.com/repos/danielschlaugies/latex-template-gh-actions/actions/artifacts"

        r = requests.get(url, headers=headers)
        if r.status_code != 200:

            # TODO
            pass
        artifacts_response = r.json()
        artifacts = artifacts_response["artifacts"]
        valid_artifacts = [artifact for artifact in artifacts if artifact["expired"] is False]
        if not valid_artifacts:
            raise HTTPException(status_code=404, detail="No artifacts found")

        latest_artifact = max(valid_artifacts, key=lambda artifact: artifact["updated_at"])
        artifact_url = latest_artifact["archive_download_url"]

        file_request = requests.get(artifact_url, headers=headers)
        if file_request.status_code != 200:
            # TODO
            pass

        in_memory_file = io.BytesIO(file_request.content)

        with zipfile.ZipFile(in_memory_file) as myzip:
            with myzip.open("main.pdf") as mypdf:
                return Response(mypdf.read(), media_type="application/pdf")


@app.get("/github/callback")
async def github_callback(code: str):
    token_data = exchange_code(code)
    token = token_data["access_token"]

    session_id = uuid.uuid4()
    sessions[session_id] = token

    redirect = RedirectResponse("/")
    redirect.set_cookie(key="session_id", value=str(session_id))

    return redirect


def exchange_code(code):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
    }
    headers = {"accept": "application/json"}

    r = requests.post("https://github.com/login/oauth/access_token", headers=headers, data=data)

    if r.status_code != 200:
        # TODO
        pass


    return r.json()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5001, reload=True)
