from discord import opus

OPUS_LIBS = ['libopus-0.x86.dll', 'libopus-0.x64.dll', 'libopus-0.dll', 'libopus.so.0', 'libopus.0.dylib']

def load_opus_libs(opus_libs=OPUS_LIBS):
    if opus.is_loaded():
        return

    for opus_lib in opus_libs:
        try:
            opus.load_opus(opus_lib)
        except OSError:
            pass