"""Decode local browser evidence into inspectable frames and a bounded QA receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path


def inspect(video: Path, output: Path, require_motion: bool = False) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to overwrite video QA evidence")
    if video.is_symlink() or not video.is_file() or not 0 < video.stat().st_size <= 128 * 1024 * 1024:
        raise ValueError("video must be a bounded nonempty regular file")
    from PIL import Image, ImageStat

    output.mkdir(parents=True, mode=0o700)
    metadata = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height:format=duration", "-of", "json", str(video.resolve())], timeout=20))
    duration = float(metadata["format"]["duration"])
    stream = metadata["streams"][0]
    if not math.isfinite(duration) or duration <= 0 or not 0 < stream["width"] <= 4096 or not 0 < stream["height"] <= 4096:
        raise ValueError("video dimensions or duration are invalid")
    frames = []
    for index, fraction in enumerate((0.1, 0.5, 0.9)):
        at = duration * fraction
        target = output / f"frame-{index}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-n", "-ss", str(at),
                        "-i", str(video.resolve()), "-frames:v", "1", str(target)], check=True, timeout=30)
        with Image.open(target) as image:
            image.load()
            stats = ImageStat.Stat(image.convert("RGB"))
            frames.append({"file": target.name, "seconds": at, "mean": stats.mean, "stddev": stats.stddev,
                           "nonblank": max(stats.stddev) > 10, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    changing = len({frame["sha256"] for frame in frames}) > 1
    report = {"schema": "world-engine.video-qa.v1", "video": str(video.absolute()),
              "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(), "video_bytes": video.stat().st_size,
              "duration_seconds": duration, "stream": stream, "frames": frames,
              "changing_frames": changing, "motion_required": require_motion,
              "passed": all(frame["nonblank"] for frame in frames) and (changing or not require_motion),
              "limits": "Pixel variation checks decoded recording, not task success or semantic fidelity; inspect frames visually."}
    with (output / "receipt.json").open("x") as file:
        json.dump(report, file, indent=2, sort_keys=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--require-motion", action="store_true")
    args = parser.parse_args()
    report = inspect(args.video, args.output, args.require_motion)
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
