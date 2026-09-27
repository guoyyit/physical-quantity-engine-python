import uvicorn

from .service import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("pqe.__main__:app", host="127.0.0.1", port=8000)
