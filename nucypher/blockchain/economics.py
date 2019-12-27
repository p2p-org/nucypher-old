"""
This file is part of nucypher.

nucypher is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

nucypher is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with nucypher.  If not, see <https://www.gnu.org/licenses/>.
"""


from decimal import Decimal, localcontext
from math import log
from typing import Tuple

from nucypher.blockchain.eth.agents import ContractAgency, NucypherTokenAgent, StakingEscrowAgent, AdjudicatorAgent, \
    WorkLockAgent
from nucypher.blockchain.eth.registry import BaseContractRegistry
from nucypher.blockchain.eth.token import NU

LOG2 = Decimal(log(2))


class BaseEconomics:
    """
    A representation of a contract deployment set's constructor parameters, and the calculations
    used to generate those values from high-level human-understandable parameters.

    --------------------------

    Formula for staking in one period:
    (totalSupply - currentSupply) * (lockedValue / totalLockedValue) * (k1 + allLockedPeriods) / k2

    K2 - Staking coefficient
    K1 - Locked periods coefficient

    if allLockedPeriods > maximum_rewarded_periods then allLockedPeriods = maximum_rewarded_periods
    kappa * log(2) / halving_delay === (k1 + allLockedPeriods) / k2

    """

    nickname = NotImplemented
    description = NotImplemented

    # Token Denomination
    __token_decimals = 18
    nunits_per_token = 10 ** __token_decimals  # Smallest unit designation

    # Period Definition
    __default_hours_per_period = 24

    # Time Constraints
    __default_minimum_worker_periods = 2
    __default_minimum_locked_periods = 30  # 720 Hours minimum

    # Value Constraints
    __default_minimum_allowed_locked = NU(15_000, 'NU').to_nunits()
    __default_maximum_allowed_locked = NU(4_000_000, 'NU').to_nunits()

    # Slashing parameters
    HASH_ALGORITHM_KECCAK256 = 0
    HASH_ALGORITHM_SHA256 = 1
    HASH_ALGORITHM_RIPEMD160 = 2

    __default_hash_algorithm = HASH_ALGORITHM_SHA256
    __default_base_penalty = 100
    __default_penalty_history_coefficient = 10
    __default_percentage_penalty_coefficient = 8
    __default_reward_coefficient = 2

    def __init__(self,

                 # StakingEscrow
                 initial_supply: int,
                 total_supply: int,
                 staking_coefficient: int,
                 locked_periods_coefficient: int,
                 maximum_rewarded_periods: int,
                 hours_per_period: int = __default_hours_per_period,
                 minimum_locked_periods: int = __default_minimum_locked_periods,
                 minimum_allowed_locked: int = __default_minimum_allowed_locked,
                 maximum_allowed_locked: int = __default_maximum_allowed_locked,
                 minimum_worker_periods: int = __default_minimum_worker_periods,

                 # Adjudicator
                 hash_algorithm: int = __default_hash_algorithm,
                 base_penalty: int = __default_base_penalty,
                 penalty_history_coefficient: int = __default_penalty_history_coefficient,
                 percentage_penalty_coefficient: int = __default_percentage_penalty_coefficient,
                 reward_coefficient: int = __default_reward_coefficient,

                 # WorkLock
                 bidding_start_date: int = NotImplemented,
                 bidding_end_date: int = NotImplemented,
                 worklock_supply: int = NotImplemented,
                 worklock_deposit_rate: int = NotImplemented,
                 worklock_refund_rate: int = NotImplemented,
                 worklock_commitment_duration: int = NotImplemented):

        """
        :param initial_supply: Tokens at t=0
        :param total_supply: Tokens at t=8
        :param staking_coefficient: K2
        :param locked_periods_coefficient: K1
        :param maximum_rewarded_periods: Max periods that will be additionally rewarded
        :param hours_per_period: Hours in single period
        :param minimum_locked_periods: Min amount of periods during which tokens can be locked
        :param minimum_allowed_locked: Min amount of tokens that can be locked
        :param maximum_allowed_locked: Max amount of tokens that can be locked
        :param minimum_worker_periods: Min amount of periods while a worker can't be changed

        :param hash_algorithm: Hashing algorithm
        :param base_penalty: Base for the penalty calculation
        :param penalty_history_coefficient: Coefficient for calculating the penalty depending on the history
        :param percentage_penalty_coefficient: Coefficient for calculating the percentage penalty
        :param reward_coefficient: Coefficient for calculating the reward
        """

        #
        # WorkLock
        #

        self.bidding_start_date = bidding_start_date
        self.bidding_end_date = bidding_end_date
        self.worklock_supply = worklock_supply
        self.worklock_deposit_rate = worklock_deposit_rate
        self.worklock_refund_rate = worklock_refund_rate
        self.worklock_commitment_duration = worklock_commitment_duration

        #
        # NucypherToken & Staking Escrow
        #

        self.initial_supply = initial_supply
        # Remaining / Reward Supply - Escrow Parameter
        self.reward_supply = total_supply - initial_supply
        self.total_supply = total_supply
        self.staking_coefficient = staking_coefficient
        self.locked_periods_coefficient = locked_periods_coefficient
        self.maximum_rewarded_periods = maximum_rewarded_periods
        self.hours_per_period = hours_per_period
        self.minimum_locked_periods = minimum_locked_periods
        self.minimum_allowed_locked = minimum_allowed_locked
        self.maximum_allowed_locked = maximum_allowed_locked
        self.minimum_worker_periods = minimum_worker_periods
        self.seconds_per_period = hours_per_period * 60 * 60  # Seconds in single period

        #
        # Adjudicator
        #

        self.hash_algorithm = hash_algorithm
        self.base_penalty = base_penalty
        self.penalty_history_coefficient = penalty_history_coefficient
        self.percentage_penalty_coefficient = percentage_penalty_coefficient
        self.reward_coefficient = reward_coefficient

    @property
    def erc20_initial_supply(self) -> int:
        return int(self.initial_supply)

    @property
    def erc20_reward_supply(self) -> int:
        return int(self.reward_supply)

    @property
    def erc20_total_supply(self) -> int:
        return int(self.total_supply)

    @property
    def staking_deployment_parameters(self) -> Tuple[int, ...]:
        """Cast coefficient attributes to uint256 compatible type for solidity+EVM"""
        deploy_parameters = (

            # Period
            self.hours_per_period,            # Hours in single period

            # Coefficients
            self.staking_coefficient,         # Staking coefficient (k2)
            self.locked_periods_coefficient,  # Locked periods coefficient (k1)
            self.maximum_rewarded_periods,    # Max periods that will be additionally rewarded (awarded_periods)

            # Constraints
            self.minimum_locked_periods,      # Min amount of periods during which tokens can be locked
            self.minimum_allowed_locked,      # Min amount of tokens that can be locked
            self.maximum_allowed_locked,      # Max amount of tokens that can be locked
            self.minimum_worker_periods       # Min amount of periods while a worker can't be changed
        )
        return tuple(map(int, deploy_parameters))

    @property
    def slashing_deployment_parameters(self) -> Tuple[int, ...]:
        """Cast coefficient attributes to uint256 compatible type for solidity+EVM"""
        deployment_parameters = [
            self.hash_algorithm,
            self.base_penalty,
            self.penalty_history_coefficient,
            self.percentage_penalty_coefficient,
            self.reward_coefficient
        ]
        return tuple(map(int, deployment_parameters))

    @property
    def worklock_deployment_parameters(self):
        deployment_parameters = [self.bidding_start_date,
                                 self.bidding_end_date,
                                 self.worklock_deposit_rate,
                                 self.worklock_refund_rate,
                                 self.worklock_commitment_duration]
        return tuple(map(int, deployment_parameters))


class StandardTokenEconomics(BaseEconomics):
    """
    --------------------------

    Formula for staking in one period:
    (totalSupply - currentSupply) * (lockedValue / totalLockedValue) * (k1 + allLockedPeriods) / k2

    K2 - Staking coefficient
    K1 - Locked periods coefficient

    if allLockedPeriods > maximum_rewarded_periods then allLockedPeriods = maximum_rewarded_periods
    kappa * log(2) / halving_delay === (k1 + allLockedPeriods) / k2

    ...but also...

    kappa = small_stake_multiplier + (1 - small_stake_multiplier) * min(T, T1) / T1
    where allLockedPeriods == min(T, T1)

    --------------------------

    Academic Reference:

    NuCypher: Mining & Staking Economics - Michael Egorov, MacLane Wilkison, NuCypher
    <https://github.com/nucypher/mining-paper/blob/master/mining-paper.pdf>

    """

    nickname = 'standard-economics'
    description = 'The same old economics you are used to.'

    # Decimal
    _precision = 28

    # Supply
    __default_initial_supply = NU(int(1_000_000_000), 'NU').to_nunits()
    __default_initial_inflation = 1
    __default_token_halving = 2      # years
    __default_reward_saturation = 1  # years
    __default_small_stake_multiplier = Decimal(0.5)

    def __init__(self,
                 initial_supply: int = __default_initial_supply,
                 initial_inflation: int = __default_initial_inflation,
                 halving_delay: int = __default_token_halving,
                 reward_saturation: int = __default_reward_saturation,
                 small_stake_multiplier: Decimal = __default_small_stake_multiplier,
                 **kwargs):
        """
        :param initial_supply: Tokens at t=0
        :param initial_inflation: Inflation on day 1 expressed in units of year**-1
        :param halving_delay: Time for inflation halving in years
        :param reward_saturation: "saturation" time - if staking is longer than T_sat, the reward doesn't get any higher
        :param small_stake_multiplier: Fraction of maximum reward rate paid to those who are about to unlock tokens
        """

        #
        # Calculated
        #

        with localcontext() as ctx:
            ctx.prec = self._precision

            initial_supply = Decimal(initial_supply)

            # ERC20 Token parameter (See Equation 4 in Mining paper)
            total_supply = initial_supply * (1 + initial_inflation * halving_delay / LOG2)

            # k2 - Escrow parameter
            staking_coefficient = 365 ** 2 * reward_saturation * halving_delay / LOG2 / (1 - small_stake_multiplier)

            # k1 - Escrow parameter
            locked_periods_coefficient = 365 * reward_saturation * small_stake_multiplier / (1 - small_stake_multiplier)

            # Awarded periods- Escrow parameter
            maximum_rewarded_periods = reward_saturation * 365

        #
        # Injected
        #

        self.initial_inflation = initial_inflation
        self.token_halving = halving_delay
        self.token_saturation = reward_saturation
        self.small_stake_multiplier = small_stake_multiplier

        super().__init__(initial_supply=initial_supply,
                         total_supply=total_supply,
                         staking_coefficient=staking_coefficient,
                         locked_periods_coefficient=locked_periods_coefficient,
                         maximum_rewarded_periods=maximum_rewarded_periods,
                         **kwargs)

    def token_supply_at_period(self, period: int) -> int:
        if period < 0:
            raise ValueError("Period must be a positive integer")

        with localcontext() as ctx:
            ctx.prec = self._precision

            #
            # Eq. 3 of the mining paper
            # https://github.com/nucypher/mining-paper/blob/master/mining-paper.pdf
            #

            t = Decimal(period)
            S_0 = self.erc20_initial_supply
            i_0 = 1
            I_0 = i_0 * S_0  # in 1/years
            T_half = self.token_halving  # in years
            T_half_in_days = T_half * 365

            S_t = S_0 + I_0 * T_half * (1 - 2**(-t / T_half_in_days)) / LOG2
            return int(S_t)

    def cumulative_rewards_at_period(self, period: int) -> int:
        return self.token_supply_at_period(period) - self.erc20_initial_supply

    def rewards_during_period(self, period: int) -> int:
        return self.cumulative_rewards_at_period(period) - self.cumulative_rewards_at_period(period-1)


class TestEconomics(StandardTokenEconomics):

    nickname = 'test-economics'
    description = f'Identical to {StandardTokenEconomics.nickname} with Instant-start one-hour worklock.'

    __default_worklock_deposit_rate = 100
    __default_worklock_refund_rate = 200
    __default_worklock_supply = NotImplemented

    def __init__(self,
                 worklock_deposit_rate: int = __default_worklock_deposit_rate,
                 worklock_refund_rate: int = __default_worklock_refund_rate,
                 worklock_supply: int = __default_worklock_supply,
                 *args, **kwargs):

        #
        # Injected
        #

        super().__init__(worklock_deposit_rate=worklock_deposit_rate,
                         worklock_refund_rate=worklock_refund_rate,
                         worklock_supply=worklock_supply,
                         *args, **kwargs)

        #
        # Calculated
        #

        self.worklock_supply = self.maximum_allowed_locked

        # TODO: Move to Standard Economics
        self.maximum_bid = int(self.maximum_allowed_locked // self.worklock_deposit_rate)
        self.minimum_bid = int(self.minimum_allowed_locked // self.worklock_deposit_rate)

    @property
    def worklock_deployment_parameters(self):
        """Lazy"""
        from nucypher.blockchain.eth.interfaces import BlockchainInterfaceFactory
        # from nucypher.utilities.sandbox.constants import TEST_PROVIDER_URI

        # Get current blocktime
        blockchain = BlockchainInterfaceFactory.get_interface()
        now = blockchain.w3.eth.getBlock(block_identifier='latest').timestamp

        # Calculate instant start time
        one_hour_in_seconds = (60 * 60)
        start_date = now
        self.bidding_start_date = start_date
        self.bidding_end_date = start_date + one_hour_in_seconds
        self.worklock_commitment_duration = 2 * self.minimum_locked_periods

        deployment_parameters = [self.bidding_start_date,
                                 self.bidding_end_date,
                                 self.worklock_deposit_rate,
                                 self.worklock_refund_rate,
                                 self.worklock_commitment_duration]
        return tuple(map(int, deployment_parameters))


class EconomicsFactory:
    # TODO: Enforce singleton

    __economics = dict()

    @classmethod
    def get_economics(cls, registry: BaseContractRegistry) -> BaseEconomics:
        registry_id = registry.id
        try:
            return cls.__economics[registry_id]
        except KeyError:
            economics = EconomicsFactory.retrieve_from_blockchain(registry=registry)
            cls.__economics[registry_id] = economics
            return economics

    @staticmethod
    def retrieve_from_blockchain(registry: BaseContractRegistry) -> BaseEconomics:
        token_agent = ContractAgency.get_agent(NucypherTokenAgent, registry=registry)
        staking_agent = ContractAgency.get_agent(StakingEscrowAgent, registry=registry)
        adjudicator_agent = ContractAgency.get_agent(AdjudicatorAgent, registry=registry)
        worklock_agent = ContractAgency.get_agent(WorkLockAgent, registry=registry)

        total_supply = token_agent.contract.functions.totalSupply().call()
        reward_supply = staking_agent.contract.functions.getReservedReward().call()
        # it's not real initial_supply value because used current reward instead of initial
        initial_supply = total_supply - reward_supply

        staking_parameters = list(staking_agent.staking_parameters())
        seconds_per_period = staking_parameters.pop(0)
        staking_parameters.insert(3, seconds_per_period // 60 // 60)  # hours_per_period
        slashing_parameters = adjudicator_agent.slashing_parameters()

        # TODO: How to get worklock supply?
        worklock_parameters = worklock_agent.worklock_parameters()

        economics_parameters = (initial_supply,
                                total_supply,
                                *staking_parameters,
                                *slashing_parameters,
                                *worklock_parameters)

        economics = BaseEconomics(*economics_parameters)
        return economics
