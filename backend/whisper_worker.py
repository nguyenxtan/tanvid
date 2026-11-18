"""Fresh-process, offline native Metal inference and resource measurements."""

import json
from pathlib import Path
import platform
import resource
import sys
import time
import wave


def main():
    import mlx.core as mx
    import mlx_whisper
    import numpy as np
    from mlx_whisper.transcribe import ModelHolder
    from backend.transcription import OPTIONS

    if platform.system() != 'Darwin' or platform.machine() != 'arm64' or not mx.metal.is_available():
        raise RuntimeError('Native Apple Silicon with Metal is required')
    mx.set_default_device(mx.gpu)
    # Bound MLX allocator to 8 GiB on the target 16 GiB host.
    mx.set_memory_limit(8 * 1024**3)
    with wave.open(sys.argv[1], 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('Expected validated PCM16 mono 16kHz WAV')
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768
    mx.reset_peak_memory()
    started = time.perf_counter()
    ModelHolder.get_model(sys.argv[2], mx.float16)
    mx.synchronize()
    loaded = time.perf_counter()
    result = mlx_whisper.transcribe(data, path_or_hf_repo=sys.argv[2], verbose=None, **OPTIONS)
    mx.synchronize()
    finished = time.perf_counter()
    metrics = {'model_load_seconds': loaded - started, 'inference_seconds': finished - loaded,
               'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               'mlx_peak_bytes': mx.get_peak_memory(), 'device': str(mx.default_device()),
               'architecture': platform.machine()}
    Path(sys.argv[3]).write_text(json.dumps({'segments': result['segments'], 'metrics': metrics}, ensure_ascii=False, allow_nan=False))


if __name__ == '__main__':
    main()
