import uvicorn

if __name__ == "__main__":
    # Bound to localhost only; nothing outside this machine can reach it.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
