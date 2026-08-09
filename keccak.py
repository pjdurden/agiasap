"""
Keccak-256 and EIP-55 address checksums, in pure Python.

hashlib.sha3_256 is NOT this. SHA-3 pads with 0x06 and Ethereum's Keccak-256
pads with 0x01, so they produce different digests for the same input. There is
no Keccak in the standard library and this repository has no dependencies, so
it lives here.

Used for one thing: refusing to publish a mistyped wallet address. A wrong
character on the funding section means donations that arrive nowhere.
"""

RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]

MASK = (1 << 64) - 1


def _rotl(x: int, n: int) -> int:
    n %= 64
    return ((x << n) | (x >> (64 - n))) & MASK


def _keccak_f(a: list[list[int]]) -> None:
    for rnd in range(24):
        # theta
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x][y] ^= d[x]

        # rho and pi
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rotl(a[x][y], ROT[x][y])

        # chi
        for x in range(5):
            for y in range(5):
                a[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y] & MASK)

        # iota
        a[0][0] ^= RC[rnd]


def keccak256(data: bytes) -> bytes:
    rate = 136  # bits 1088, capacity 512
    a = [[0] * 5 for _ in range(5)]

    # Original Keccak padding: 0x01 ... 0x80. SHA-3 would use 0x06 here.
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    for off in range(0, len(padded), rate):
        block = padded[off:off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8:(i + 1) * 8], "little")
            a[i % 5][i // 5] ^= lane
        _keccak_f(a)

    out = bytearray()
    while len(out) < 32:
        for i in range(rate // 8):
            if len(out) >= 32:
                break
            out += a[i % 5][i // 5].to_bytes(8, "little")
    return bytes(out[:32])


def to_checksum_address(address: str) -> str:
    """Return the EIP-55 mixed-case form of a 0x-prefixed hex address."""
    raw = address.lower().removeprefix("0x")
    digest = keccak256(raw.encode()).hex()
    return "0x" + "".join(
        ch.upper() if ch.isalpha() and int(digest[i], 16) >= 8 else ch
        for i, ch in enumerate(raw)
    )


def is_checksum_address(address: str) -> bool:
    """
    True if the address carries a valid EIP-55 checksum.

    An all-lowercase or all-uppercase address has no checksum to verify and
    returns False, so callers must decide whether to require one.
    """
    body = address.removeprefix("0x")
    if body.islower() or body.isupper():
        return False
    return address == to_checksum_address(address)
