"""Run in a SEPARATE Style-Bert-VITS2 environment; heavyweight imports stay in the worker.

python -m app.providers.tts.bridge --assets /path/to/assets.json --port 5000
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import multiprocessing
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import Field

from app.core.json_config import StrictConfig, read_json


class Assets(StrictConfig):
    model_path: Path
    config_path: Path
    style_vectors_path: Path
    bert_paths: dict[Literal["JP", "EN", "ZH"], Path] = Field(min_length=1)
    device: Literal["cpu", "cuda"] = "cpu"
    license_reference: str = Field(min_length=1)
    approved: Literal[True]


class Synthesis(StrictConfig):
    text: str = Field(min_length=1, max_length=2000)
    speaker_id: int = Field(0, ge=0)
    model_id: Literal[0] = 0
    language: Literal["JP", "EN", "ZH"] = "EN"
    style: str = Field("Neutral", min_length=1, max_length=100)


def worker(connection, assets: dict) -> None:
    # Never allow third-party libraries to print text, paths, or inference diagnostics.
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        import numpy as np
        from style_bert_vits2.constants import Languages
        from style_bert_vits2.logging import logger
        from style_bert_vits2.nlp import bert_models
        from style_bert_vits2.tts_model import TTSModel

        logger.remove()
        model = TTSModel(
            model_path=Path(assets["model_path"]),
            config_path=Path(assets["config_path"]),
            style_vec_path=Path(assets["style_vectors_path"]),
            device=assets["device"],
        )
        while True:
            value = connection.recv()
            language = Languages(value["language"])
            bert_path = assets["bert_paths"].get(value["language"])
            if not bert_path or not Path(bert_path).is_dir():
                connection.send({"error": "language_assets_missing"})
                continue
            bert_models.load_model(language, pretrained_model_name_or_path=bert_path, device_map=assets["device"])
            bert_models.load_tokenizer(language, pretrained_model_name_or_path=bert_path)
            rate, audio = model.infer(
                text=value["text"], language=value["language"], speaker_id=value["speaker_id"], style=value["style"]
            )
            if audio.dtype.kind == "f":
                audio = np.nan_to_num(audio)
                audio = (np.clip(audio, -1, 1) * 32767).astype("<i2")
            else:
                audio = audio.astype("<i2")
            if audio.ndim != 1 or audio.nbytes > 16_000_000:
                connection.send({"error": "invalid_audio"})
            else:
                connection.send({"rate": int(rate), "pcm": audio.tobytes()})
    except (Exception, EOFError):
        try:
            connection.send({"error": "inference_failed"})
        except (EOFError, OSError):
            pass
    finally:
        connection.close()


class Synthesizer:
    def __init__(self, assets: Assets) -> None:
        self.assets = assets
        self.process = None
        self.connection = None
        self.lock = asyncio.Lock()

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
            self.process.close()
            self.process = None
        if self.connection:
            self.connection.close()
            self.connection = None

    def start(self) -> None:
        if self.process and self.process.is_alive():
            return
        self.stop()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        self.connection = parent
        self.process = context.Process(target=worker, args=(child, self.assets.model_dump(mode="json")), daemon=True)
        self.process.start()
        child.close()

    async def synthesize(self, value: Synthesis, request: Request) -> dict:
        async with self.lock:
            if await request.is_disconnected():
                raise HTTPException(499, "cancelled")
            self.start()
            try:
                self.connection.send(value.model_dump())
                async with asyncio.timeout(115):
                    while not self.connection.poll():
                        if await request.is_disconnected():
                            raise HTTPException(499, "cancelled")
                        await asyncio.sleep(0.05)
                    result = self.connection.recv()
                if "error" in result:
                    raise HTTPException(503, "inference_failed")
                return result
            except BaseException:
                self.stop()  # Cancellation stops synthesis and releases worker GPU memory.
                raise


def create_app(assets: Assets) -> FastAPI:
    synthesizer = Synthesizer(assets)

    @asynccontextmanager
    async def lifespan(app):
        yield
        synthesizer.stop()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    async def health():
        paths = (assets.model_path, assets.config_path, assets.style_vectors_path)
        return {
            "ready": all(path.is_file() for path in paths)
            and all(path.is_dir() for path in assets.bert_paths.values())
            and importlib.util.find_spec("style_bert_vits2") is not None,
            "worker_loaded": bool(synthesizer.process and synthesizer.process.is_alive()),
        }

    @app.post("/synthesize")
    async def synthesize(value: Synthesis, request: Request):
        try:
            result = await synthesizer.synthesize(value, request)
            return Response(
                result["pcm"], media_type="application/octet-stream", headers={"x-sample-rate": str(result["rate"])}
            )
        except (TimeoutError, OSError, EOFError):
            raise HTTPException(503, "synthesis_unavailable") from None

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    assets = read_json(args.assets, Assets)
    for field in ("model_path", "config_path", "style_vectors_path"):
        path = getattr(assets, field)
        if not path.is_absolute():
            setattr(assets, field, (args.assets.resolve().parent / path).resolve())
    assets.bert_paths = {
        language: path if path.is_absolute() else (args.assets.resolve().parent / path).resolve()
        for language, path in assets.bert_paths.items()
    }
    import uvicorn

    uvicorn.run(create_app(assets), host="127.0.0.1", port=args.port, access_log=False, log_level="critical")


if __name__ == "__main__":
    main()
