import math
import struct
import time
import zlib


BLOCK_SIZE = 16
DEFAULT_LOG_ENCRYPT_KEY = "I+D&*76:j27kVH<us9&d"

SBOX0 = [
    99, 124, 119, 123, 242, 107, 111, 197, 48, 1, 103, 43, 254, 215, 171, 118,
    202, 130, 201, 125, 250, 89, 71, 240, 173, 212, 162, 175, 156, 164, 114, 192,
    183, 253, 147, 38, 54, 63, 247, 204, 52, 165, 229, 241, 113, 216, 49, 21,
    4, 199, 35, 195, 24, 150, 5, 154, 7, 18, 128, 226, 235, 39, 178, 117,
    9, 131, 44, 26, 27, 110, 90, 160, 82, 59, 214, 179, 41, 227, 47, 132,
    83, 209, 0, 237, 32, 252, 177, 91, 106, 203, 190, 57, 74, 76, 88, 207,
    208, 239, 170, 251, 67, 77, 51, 133, 69, 249, 2, 127, 80, 60, 159, 168,
    81, 163, 64, 143, 146, 157, 56, 245, 188, 182, 218, 33, 16, 255, 243, 210,
    205, 12, 19, 236, 95, 151, 68, 23, 196, 167, 126, 61, 100, 93, 25, 115,
    96, 129, 79, 220, 34, 42, 144, 136, 70, 238, 184, 20, 222, 94, 11, 219,
    224, 50, 58, 10, 73, 6, 36, 92, 194, 211, 172, 98, 145, 149, 228, 121,
    231, 200, 55, 109, 141, 213, 78, 169, 108, 86, 244, 234, 101, 122, 174, 8,
    186, 120, 37, 46, 28, 166, 180, 198, 232, 221, 116, 31, 75, 189, 139, 138,
    112, 62, 181, 102, 72, 3, 246, 14, 97, 53, 87, 185, 134, 193, 29, 158,
    225, 248, 152, 17, 105, 217, 142, 148, 155, 30, 135, 233, 206, 85, 40, 223,
    140, 161, 137, 13, 191, 230, 66, 104, 65, 153, 45, 15, 176, 84, 187, 22,
]

SBOX1 = [
    82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
    124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
    84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
    8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37,
    114, 248, 246, 100, 134, 104, 152, 22, 212, 164, 92, 204, 93, 101, 182, 146,
    108, 112, 72, 80, 253, 237, 185, 218, 94, 21, 70, 87, 167, 141, 157, 132,
    144, 216, 171, 0, 140, 188, 211, 10, 247, 228, 88, 5, 184, 179, 69, 6,
    208, 44, 30, 143, 202, 63, 15, 2, 193, 175, 189, 3, 1, 19, 138, 107,
    58, 145, 17, 65, 79, 103, 220, 234, 151, 242, 207, 206, 240, 180, 230, 115,
    150, 172, 116, 34, 231, 173, 53, 133, 226, 249, 55, 232, 28, 117, 223, 110,
    71, 241, 26, 113, 29, 41, 197, 137, 111, 183, 98, 14, 170, 24, 190, 27,
    252, 86, 62, 75, 198, 210, 121, 32, 154, 219, 192, 254, 120, 205, 90, 244,
    31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
    96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
    160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
    23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125,
]


def _u8(value):
    return value & 0xFF


def _u32(value):
    return value & 0xFFFFFFFF


def _rotl32(value, amount):
    value = _u32(value)
    return _u32((value << amount) | (value >> (32 - amount)))


def _utf16_code_units(text):
    raw = text.encode("utf-16-le", "surrogatepass")
    return [raw[i] | (raw[i + 1] << 8) for i in range(0, len(raw), 2)]


def _write_utf_js(text):
    out = []
    for code in _utf16_code_units(str(text)):
        if 0 <= code <= 127:
            out.append(code)
        elif 128 <= code <= 2047:
            out.append(192 | ((31 & code) >> 6))
            out.append(128 | (63 & code))
        elif (2048 <= code <= 55295) or (57344 <= code <= 65535):
            out.append(224 | ((15 & code) >> 12))
            out.append(128 | ((63 & code) >> 6))
            out.append(128 | (63 & code))
    return [_u8(x) for x in out]


def _js_strlen(text):
    return len(_utf16_code_units(str(text)))


def _derive_std_key(key):
    key_bytes = [0] * 16
    utf_bytes = _write_utf_js(key)
    copy_size = 16
    key_len = _js_strlen(key)
    if key_len < 16:
        copy_size = key_len

    for idx in range(copy_size):
        key_bytes[idx] = utf_bytes[idx] if idx < len(utf_bytes) else 0

    for idx in range(copy_size, 16):
        key_bytes[idx] = SBOX1[key_bytes[idx - copy_size]]

    for idx in range(16):
        key_bytes[idx] = SBOX0[key_bytes[idx]]

    words = []
    for idx in range(0, 16, 4):
        words.append(
            _u32(
                (key_bytes[idx] << 24)
                | (key_bytes[idx + 1] << 16)
                | (key_bytes[idx + 2] << 8)
                | key_bytes[idx + 3]
            )
        )
    return words


def _bytes_to_words(block):
    return [
        _u32((block[0] << 24) | (block[1] << 16) | (block[2] << 8) | block[3]),
        _u32((block[4] << 24) | (block[5] << 16) | (block[6] << 8) | block[7]),
        _u32((block[8] << 24) | (block[9] << 16) | (block[10] << 8) | block[11]),
        _u32((block[12] << 24) | (block[13] << 16) | (block[14] << 8) | block[15]),
    ]


def _words_to_bytes(words):
    out = []
    for word in words:
        word = _u32(word)
        out.extend([(word >> 24) & 0xFF, (word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF])
    return out


def _xor_mix(std_key, block):
    e, t, i, v = _bytes_to_words(block)
    e = _u32(e ^ std_key[0])
    t = _u32(t ^ std_key[1])
    i = _u32(i ^ std_key[2])
    v = _u32(v ^ std_key[3])
    return _words_to_bytes([e, t, i, v])


def _rot_transform_encrypt(block):
    first, second, third, fourth = _bytes_to_words(block)
    return _words_to_bytes([
        _u32(first),
        _rotl32(second, 8),
        _rotl32(third, 16),
        _rotl32(fourth, 24),
    ])


def _gzip_like_pako(payload_bytes, mtime=None):
    if mtime is None:
        mtime = int(time.time())

    compressor = zlib.compressobj(
        level=6,
        method=zlib.DEFLATED,
        wbits=-zlib.MAX_WBITS,
        memLevel=4,
        strategy=zlib.Z_DEFAULT_STRATEGY,
    )
    deflated = compressor.compress(payload_bytes) + compressor.flush()

    header = bytes([0x1F, 0x8B, 0x08, 0x00]) + struct.pack("<I", mtime) + bytes([0x00, 0x03])
    crc = zlib.crc32(payload_bytes) & 0xFFFFFFFF
    size = len(payload_bytes) & 0xFFFFFFFF
    trailer = struct.pack("<II", crc, size)
    return header + deflated + trailer


def log_encrypt(payload_text, magic_number=29795, version=3, sub_version=3, key=DEFAULT_LOG_ENCRYPT_KEY):
    std_key = _derive_std_key(key)
    header = [
        _u8(magic_number >> 8),
        _u8(magic_number),
        _u8(version),
        0,
        _u8(sub_version >> 8),
        _u8(sub_version),
    ]

    gz = _gzip_like_pako(bytes(_write_utf_js(payload_text)))
    raw_data = list(gz)

    padded = list(raw_data)
    pad_count = BLOCK_SIZE - (len(padded) % BLOCK_SIZE)
    if pad_count == BLOCK_SIZE:
        header[3] = _u8(0)
    else:
        header[3] = _u8(pad_count)
        padded.extend([_u8(pad_count)] * pad_count)

    substituted = [SBOX0[_u8(byte)] for byte in padded]

    block_count = int(math.ceil(len(raw_data) / float(BLOCK_SIZE)))
    encrypted = []
    for idx in range(block_count):
        block = substituted[idx * BLOCK_SIZE : (idx + 1) * BLOCK_SIZE]
        block = _rot_transform_encrypt(block)
        block = _xor_mix(std_key, block)
        encrypted.extend(block)

    return bytes(header + encrypted)
