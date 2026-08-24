from fastapi import FastAPI

app = FastAPI(title="Drawings Tracker")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Drawings Tracker is ready for implementation."}
