# standard imports
import random


LEGIT_VALI_COLDKEYS = {
    "5FuzgvtfbZWdKSRxyYVPAPYNaNnf9cMnpT7phL3s2T3Kkrzo": "Rizzo",
    "5GW9X8GyXwA3VQbNhnzb6sJmfPvKBBJwx19hJrCseverjovV": "Rt21",
    "5EBuUXD6eXSSWVaT1NqaUQoAACUkAmEogzAfPQvDXTEQZ8Ff": "OTF",
    "5E9fVY1jexCNVMjd2rdBsAxeamFGEMfzHcyTn2fHgdHeYc5p": "Yuma",
    "5FHxxe8ZKYaNmGcSLdG5ekxXeZDhQnk9cbpHdsJW8RunGpSs": "Kraken",
    "5CWzmvA17MAMQ9mnAecLxFXS2N8846rz6T7m4QNHyVtJVq4j": "TAO.com",
}


WEIGHT_COPIER_COLDKEYS = {
    "5EJAqczgzCMvWcmXhKMZH4vMS5gPy8BjeuHjz5o5yN6RYzX2": "Tao5 (WC)",
    "5GsbTgfvgCH4xdqSkiPb7EaBBFLHjWH5vfEALhJaewSFpZX9": "Tao.bot (WC)",
    "5Ek8i6wDRakJfJPM9wpJLYDE9G9uaqHLdARoewtTiLtbt33f": "1T1B.AI (WC)",
    "5GP1VN5DcMNW5XL6cAFEzneN9fTfWMytNibZX8YMS7BgJBG6": "Kooltek68 (WC)",
    "5Eq8b9p6zJMjEXyH9sX4DRMYspnUyorEKq3Zmha1WN6AC4sf": "Crucible Labs (WC)",
    "5HiFDVNX4ivCJFt9RvgRCtQKmAPgAXGX8BRgX3XKqfY9fFve": "TAO.app (WC)",
    "5DkwfxC9mZTTCsRUt6nrnwQEWVrhsmY13SBRparj6cpAVxVY": "Datura",
    "5F4XcaiEBkE3ARx2kG29KJ8e94nFfUZQYC4c7zfticastxiD": "Weight Copier",
    "5DyMLUKuc6T3QFAXKd3w6dTcxmcH1WBZ1gDrRwJAnPf7N28w": "Weight Copier",
    "5EnXts8HKLv1o3qhFBGPaoZt1CjMd2g4RtKDpnp3A44xFCGK": "Weight Copier",  # 5FLoWC...SeRv8m
    "5CqsgERpW6dJn4AtTkfckcUd7Ab6JNVa2Hb2MhyjApYVXMUV": "MUV",
    "5DywxdtESjskgPZrDXL86qV44SpPgJuqs9X6noyJJwX9PaSD": "General Tensor",
}


def _create_get_lite_subtensor_network():
    # Local lite subtensor names.
    local_lite_subtensors = [
        "cali",
        "candyland",
        "datacenter01",
        "la",
        "moonbase",
        "titan",
    ]

    # Randomize local subtensor.
    random.seed()
    local_subtensor_index = random.randint(0, len(local_lite_subtensors) - 1)

    def get_network(name=None):

        def get_network_from_name(name):
            return name if ":" in name else f"ws://subtensor-{name}.rizzo.network:9944"
        
        if name is False:
            return "finney"

        if name is None:
            nonlocal local_subtensor_index
            local_subtensor_index = (local_subtensor_index + 1) % len(local_lite_subtensors)
            name = local_lite_subtensors[local_subtensor_index]

        return get_network_from_name(name)
    
    return get_network


get_lite_subtensor_network = _create_get_lite_subtensor_network()
