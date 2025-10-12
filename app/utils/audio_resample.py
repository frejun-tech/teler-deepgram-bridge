import numpy as np
from scipy.signal import resample

def downsample_pcm16(raw_bytes: bytes, input_rate=16000, output_rate=8000) -> bytes:
    """
    Downsample PCM16 mono audio bytes from input_rate to output_rate.
    Convert bytes → numpy array of int16
    """
    audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
    new_length = int(len(audio_np) * output_rate / input_rate)
    resampled_audio = resample(audio_np, new_length).astype(np.int16)
    return resampled_audio.tobytes()
