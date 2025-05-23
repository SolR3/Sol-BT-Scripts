import logging

from bittensor_wallet.bittensor_wallet import Wallet
from patrol.validation.scoring import MinerScoreRepository
from bittensor.core.async_subtensor import AsyncSubtensor

logger = logging.getLogger(__name__)

class WeightSetter:

    def __init__(self,
                 miner_score_repository: MinerScoreRepository,
                 subtensor: AsyncSubtensor,
                 wallet: Wallet,
                 net_uid: int
    ):
        self.miner_score_repository = miner_score_repository
        self.subtensor = subtensor
        self.wallet = wallet
        self.net_uid = net_uid

    async def calculate_weights(self):
        overall_scores = await self.miner_score_repository.find_last_average_overall_scores()

        metagraph = await self.subtensor.metagraph(self.net_uid)
        miners = list(zip(metagraph.hotkeys, metagraph.uids.tolist()))

        scores_to_convert = {k: v for k, v in overall_scores.items() if k in miners}

        sum_of_scores = sum(scores_to_convert.values())
        if sum_of_scores == 0:
            return {}

        overall_weights = {k: v / sum_of_scores for k, v in scores_to_convert.items()}
        return overall_weights

    async def set_weights(self, weights: dict[tuple[str, int], float]):
        if not weights:
            logger.info("No weights to set.")
            return

        _, uids = zip(*weights.keys())

        weight_values = list(weights.values())
        uid_values = list(uids)

        max_retries = 20
        delay_between_retries = 12  # seconds
        for attempt in range(max_retries):
            try:
                result = await self.subtensor.set_weights(
                    wallet=self.wallet,
                    netuid=self.net_uid,
                    uids=uid_values,
                    weights=weight_values,
                    wait_for_inclusion=True,
                    wait_for_finalization=True
                )
                logger.info(f"Sol: Result from set_weights: {result}")
                if result[0] is True:
                    weights_for_logging = {str(k): v for k, v in weights.items()}
                    logger.info("Set weights", extra=weights_for_logging)
                    break  # Exit loop if successful
            except Exception as e:
                logger.error(f"Sol: Error setting weights: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Sol: Retrying in {delay_between_retries} seconds...")
                import asyncio
                await asyncio.sleep(delay_between_retries)
            else:
                logger.error("Sol: Failed to set weights after multiple attempts. Exiting.")

    async def is_weight_setting_due(self) -> bool:
        my_hotkey = self.wallet.get_hotkey().ss58_address
        my_uid = await self.subtensor.get_uid_for_hotkey_on_subnet(my_hotkey, self.net_uid)

        blocks_since_last_update = await self.subtensor.blocks_since_last_update(self.net_uid, my_uid)
        tempo = await self.subtensor.tempo(self.net_uid)

        logger.info(f"Sol: {blocks_since_last_update=} , {tempo=}")
        return blocks_since_last_update > tempo



