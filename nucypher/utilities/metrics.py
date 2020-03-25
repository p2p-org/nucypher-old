try:
        from prometheus_client import Gauge, Enum, Counter, Info
except ImportError:
    raise ImportError('prometheus_client is not installed - Install it and try again.')
from twisted.internet import reactor, task

import nucypher
from nucypher.blockchain.eth.agents import ContractAgency, StakingEscrowAgent

from nucypher.blockchain.eth.actors import NucypherTokenActor

# Metrics
known_nodes_guage = Gauge('ursula_known_nodes', 'Number of currently known nodes')
work_orders_guage = Gauge('ursula_work_orders', 'Number of accepted work orders')
missing_confirmation_guage = Gauge('ursula_missing_confirmations', 'Currently missed confirmations')
learning_status = Enum('ursula_node_discovery', 'Learning loop status', states=['starting', 'running', 'stopped'])
eth_balance_gauge = Gauge('ursula_eth_balance', 'Ethereum balance')
token_balance_gauge = Gauge('ursula_token_balance', 'NuNit balance')
requests_counter = Counter('ursula_http_failures', 'HTTP Failures', ['method', 'endpoint'])
host_info = Info('ursula_host_info', 'Description of info')
active_stake_gauge = Gauge('ursula_active_stake', 'Active stake')


def collect_prometheus_metrics(ursula, filters, event_metrics):
    base_payload = {'app_version': nucypher.__version__,
                    'teacher_version': str(ursula.TEACHER_VERSION),
                    'host': str(ursula.rest_interface),
                    'domains': str(', '.join(ursula.learning_domains)),
                    'fleet_state': str(ursula.known_nodes.checksum),
                    'known_nodes': str(len(ursula.known_nodes))
                    }

    learning_status.state('running' if ursula._learning_task.running else 'stopped')
    known_nodes_guage.set(len(ursula.known_nodes))
    work_orders_guage.set(len(ursula.work_orders()))

    if not ursula.federated_only:

        nucypher_token_actor = NucypherTokenActor(ursula.registry, checksum_address=ursula.checksum_address)
        eth_balance_gauge.set(nucypher_token_actor.eth_balance)
        token_balance_gauge.set(nucypher_token_actor.token_balance)

        for metric_key, metric_value in event_metrics.items():
            for event in filters[metric_key].get_new_entries():
                for arg in metric_value.keys():
                    metric_value[arg].set(event['args'][arg])

        staking_agent = ContractAgency.get_agent(StakingEscrowAgent, registry=ursula.registry)
        locked = staking_agent.get_locked_tokens(staker_address=ursula.checksum_address, periods=1)
        active_stake_gauge.set(locked)

        missing_confirmations = staking_agent.get_missing_confirmations(
            checksum_address=ursula.checksum_address)  # TODO: lol
        missing_confirmation_guage.set(missing_confirmations)

        decentralized_payload = {'provider': str(ursula.provider_uri),
                                 'active_stake': str(locked),
                                 'missing_confirmations': str(missing_confirmations)}

        base_payload.update(decentralized_payload)

    host_info.info(base_payload)


def get_filters(ursula):
    staking_agent = ContractAgency.get_agent(StakingEscrowAgent, registry=ursula.registry)

    # {event_name: filter}
    filters = {
        "deposited": staking_agent.contract.events.Deposited.createFilter(fromBlock='latest',
                                                                                  argument_filters={
                                                                                      'staker': ursula.checksum_address}),
        "locked": staking_agent.contract.events.Locked.createFilter(fromBlock='latest',
                                                                            argument_filters={
                                                                                'staker': ursula.checksum_address}),
        "divided": staking_agent.contract.events.Divided.createFilter(fromBlock='latest',
                                                                                            argument_filters={
                                                                                                'staker': ursula.checksum_address}),
        "prolonged": staking_agent.contract.events.Prolonged.createFilter(fromBlock='latest',
                                                                                  argument_filters={
                                                                                      'staker': ursula.checksum_address}),
        "withdrawn": staking_agent.contract.events.Withdrawn.createFilter(fromBlock='latest',
                                                                                  argument_filters={
                                                                                      'staker': ursula.checksum_address}),
        "activity_confirmed": staking_agent.contract.events.ActivityConfirmed.createFilter(fromBlock='latest',
                                                                                                   argument_filters={
                                                                                                       'staker': ursula.checksum_address}),
        "mined": staking_agent.contract.events.Mined.createFilter(fromBlock='latest',
                                                                          argument_filters={
                                                                              'staker': ursula.checksum_address}),
        "slashed_reward": staking_agent.contract.events.Slashed.createFilter(fromBlock='latest',
                                                                                          argument_filters={
                                                                                              'investigator': ursula.checksum_address}),
        "slashed_penalty": staking_agent.contract.events.Deposited.createFilter(fromBlock='latest',
                                                                                       argument_filters={
                                                                                           'staker': ursula.checksum_address}),
        "restake_set": staking_agent.contract.events.ReStakeSet.createFilter(fromBlock='latest',
                                                                                     argument_filters={
                                                                                         'staker': ursula.checksum_address}),
        "restake_locked": staking_agent.contract.events.ReStakeLocked.createFilter(fromBlock='latest',
                                                                                                  argument_filters={
                                                                                                      'staker': ursula.checksum_address}),
        "work_measurement_set": staking_agent.contract.events.WorkMeasurementSet.createFilter(
                                                                                    fromBlock='latest',
                                                                                    argument_filters={
                                                                                        'staker': ursula.checksum_address}),
        "wind_down_set": staking_agent.contract.events.WindDownSet.createFilter(fromBlock='latest',
                                                                                  argument_filters={
                                                                                      'staker': ursula.checksum_address})}
    return filters


def initialize_prometheus_exporter(ursula, port: int) -> None:
    from prometheus_client.twisted import MetricsResource
    from twisted.web.resource import Resource
    from twisted.web.server import Site

    # {event_name: {event.argument: metric}}
    event_metrics = {
        "deposited": {"value": Gauge('ursula_deposited_value', 'Deposited value'),
                      "periods": Gauge('ursula_deposited_periods', 'Deposited periods')},
        "locked": {"value":Gauge('ursula_locked_value', 'Locked valued'),
                   "periods":Gauge('ursula_locked_periods', 'Locked periods')},
        "divided": {"newValue": Gauge('ursula_divided_new_value', 'New value of divided sub stake'),
                    "periods": Gauge('ursula_divided_periods', 'Amount of periods for extending sub stake')},
        "prolonged": {"value": Gauge('ursula_prolonged_value', 'Prolonged value'),
                      "periods": Gauge('ursula_prolonged_periods', 'Prolonged periods')},
        "withdrawn": {"value": Gauge('ursula_withdrawn_value', 'Withdrawn value')},
        "activity_confirmed": {"value": Gauge('ursula_activity_confirmed_value', 'Activity confirmed with value of locked tokens'),
                               "period": Gauge('ursula_activity_confirmed_period', 'Activity confirmed period')},
        "mined": {"value": Gauge('ursula_mined_value', 'Mined value'),
                  "period": Gauge('ursula_mined_period', 'Mined period')},
        "slashed_reward": {"reward": Gauge('ursula_slashed_reward', 'Reward for investigating slasher')},
        "slashed_penalty": {"penalty": Gauge('ursula_slashed_penalty', 'Penalty for slashing')},
        "restake_set": {"reStake": Gauge('ursula_restake_set', '')},
        "restake_locked": {"lockUntilPeriod": Gauge('ursula_restake_locked_until_period', '')},
        "work_measurement_set": {"measureWork": Gauge('ursula_work_measurement_set_measure_work', '')},
        "wind_down_set": {"windDown": Gauge('ursula_wind_down_set_wind_down', 'is windDown')}
    }

    # Scheduling
    metrics_task = task.LoopingCall(collect_prometheus_metrics, ursula=ursula, filters=get_filters(ursula), event_metrics=event_metrics)
    metrics_task.start(interval=10, now=False)  # TODO: make configurable

    # WSGI Service
    root = Resource()
    root.putChild(b'metrics', MetricsResource())
    factory = Site(root)
    reactor.listenTCP(port, factory)
