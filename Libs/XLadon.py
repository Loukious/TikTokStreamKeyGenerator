from Libs.signers import Ladon, make_ladon


def ladon_encrypt(timestamp: int, license_id: int = 1877999593, aid: int | str = "8311", **_kwargs) -> str:
    return make_ladon(timestamp, license_id, str(aid))
