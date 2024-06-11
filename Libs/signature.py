import base64
import hashlib
import ctypes
from os import urandom
from urllib.parse import urlencode
import urllib.parse

def padding_size(size: int) -> int:
    mod = size % 16
    if mod > 0:
        return size + (16 - mod)
    return size

def pkcs7_padding_data_length(buffer, buffer_size, modulus):
    if buffer_size % modulus != 0 or buffer_size < modulus:
        return 0
    padding_value = buffer[buffer_size-1]
    if padding_value < 1 or padding_value > modulus:
        return 0
    if buffer_size < padding_value + 1:
        return 0
    count = 1
    buffer_size -= 1
    for i in range(count, padding_value):
        buffer_size -= 1
        if buffer[buffer_size] != padding_value:
            return 0
    return buffer_size

def pkcs7_padding_pad_buffer(buffer: bytearray, data_length: int, buffer_size: int, modulus: int) -> int:
    pad_byte = modulus - (data_length % modulus)
    if data_length + pad_byte > buffer_size:
        return -pad_byte
    for i in range(pad_byte):
        buffer[data_length+i] = pad_byte
    return pad_byte

def md5bytes(data: bytes) -> str:
    m = hashlib.md5()
    m.update(data)
    return m.hexdigest()


def get_type_data(ptr, index, data_type):
    if data_type == "uint64_t":
        return int.from_bytes(ptr[index * 8 : (index + 1) * 8], "little")
    else:
        raise ValueError("Invalid data type")


def set_type_data(ptr, index, data, data_type):
    if data_type == "uint64_t":
        ptr[index * 8 : (index + 1) * 8] = data.to_bytes(8, "little")
    else:
        raise ValueError("Invalid data type")


def validate(num):
    return num & 0xFFFFFFFFFFFFFFFF


def __ROR__(value: ctypes.c_ulonglong, count: int) -> ctypes.c_ulonglong:
    nbits = ctypes.sizeof(value) * 8
    count %= nbits
    low = ctypes.c_ulonglong(value.value << (nbits - count)).value
    value = ctypes.c_ulonglong(value.value >> count).value
    value = value | low
    return value


def encrypt_ladon_input(hash_table, input_data):
    data0 = int.from_bytes(input_data[:8], byteorder="little")
    data1 = int.from_bytes(input_data[8:], byteorder="little")

    for i in range(0x22):
        hash = int.from_bytes(hash_table[i * 8 : (i + 1) * 8], byteorder="little")
        data1 = validate(hash ^ (data0 + ((data1 >> 8) | (data1 << (64 - 8)))))
        data0 = validate(data1 ^ ((data0 >> 0x3D) | (data0 << (64 - 0x3D))))

    output_data = bytearray(26)
    output_data[:8] = data0.to_bytes(8, byteorder="little")
    output_data[8:] = data1.to_bytes(8, byteorder="little")

    return bytes(output_data)


def encrypt_ladon(md5hex: bytes, data: bytes, size: int):
    hash_table = bytearray(272 + 16)
    hash_table[:32] = md5hex

    temp = []
    for i in range(4):
        temp.append(int.from_bytes(hash_table[i * 8 : (i + 1) * 8], byteorder="little"))

    buffer_b0 = temp[0]
    buffer_b8 = temp[1]
    temp.pop(0)
    temp.pop(0)

    for i in range(0, 0x22):
        x9 = buffer_b0
        x8 = buffer_b8
        x8 = validate(__ROR__(ctypes.c_ulonglong(x8), 8))
        x8 = validate(x8 + x9)
        x8 = validate(x8 ^ i)
        temp.append(x8)
        x8 = validate(x8 ^ __ROR__(ctypes.c_ulonglong(x9), 61))
        set_type_data(hash_table, i + 1, x8, "uint64_t")
        buffer_b0 = x8
        buffer_b8 = temp[0]
        temp.pop(0)

    new_size = padding_size(size)

    input = bytearray(new_size)
    input[:size] = data
    pkcs7_padding_pad_buffer(input, size, new_size, 16)

    output = bytearray(new_size)
    for i in range(new_size // 16):
        output[i * 16 : (i + 1) * 16] = encrypt_ladon_input(
            hash_table, input[i * 16 : (i + 1) * 16]
        )

    return output


def ladon_encrypt(
    khronos      : int,
    lc_id        : int   = 1611921764,
    aid          : int   = 8311,
    random_bytes : bytes = urandom(4)) -> str:
    
    data       = f"{khronos}-{lc_id}-{aid}"

    keygen     = random_bytes + str(aid).encode()
    md5hex     = md5bytes(keygen)

    size       = len(data)
    new_size   = padding_size(size)

    output     = bytearray(new_size + 4)
    output[:4] = random_bytes

    output[4:] = encrypt_ladon(md5hex.encode(), data.encode(), size)

    return {"x-ladon": base64.b64encode(bytes(output)).decode()}


def get_x_ss_stub(data):
    encoded_data = urlencode(data, quote_via=urllib.parse.quote).encode('utf-8')
    md5_hash = hashlib.md5(encoded_data).hexdigest()
    return {"x-ss-stub": md5_hash}

class Ladon:
    @staticmethod
    def encrypt(x_khronos: int, lc_id: str, aid: int) -> str:
        return ladon_encrypt(x_khronos, lc_id, aid)

