"""
This script evaluates the training of DQN, following the original DQN
 paper procedure, which is;

---
`The trained agents were evaluated by playing each game 30 times for up to
 5 min each time with different initial random conditions
---

"""
from __future__ import division

import os
import time
import logging

from luchador.util import load_config
from luchador.env import get_env
from luchador.agent import get_agent
from luchador.nn import SummaryWriter

_LG = logging.getLogger('luchador')


def parse_command_line_args():
    from argparse import ArgumentParser as AP
    ap = AP(description=(
        'Given a set of DQN parameters, evaluate the performace'
    ))
    ap.add_argument(
        'env', help='Envorinment configuration file'
    )
    ap.add_argument(
        'agent', help='Agent configuration file'
    )
    ap.add_argument(
        'input_dir', help='Directory where trained parameters are stored'
    )
    ap.add_argument(
        'output_dir', help='Directory where evaluation result is written'
    )
    ap.add_argument(
        '--prefix', default='DQN',
        help='Prefix of trained parameter files'
    )
    ap.add_argument(
        '--timelimit', type=float, default=300,
        help='Time limit of one episode'
    )
    ap.add_argument(
        '--episodes', type=int, default=30,
        help='#Episodes to run'
    )
    return ap.parse_args()


def load_env(cfg_file):
    cfg = load_config(cfg_file)
    Environment = get_env(cfg['name'])
    return Environment(**cfg['args'])


def load_agent(cfg_file):
    cfg = load_config(cfg_file)
    Agent = get_agent(cfg['name'])
    return Agent(**cfg['args'])


def get_parameter_files(dir_path, prefix):
    files = []
    for f in os.listdir(dir_path):
        if f.startswith(prefix):
            ite = int(f.split('.')[0].split('_')[1])
            f_path = os.path.join(dir_path, f)
            files.append((ite, f_path))
    files.sort(key=lambda f: f[0])
    return files


def run_single_episode(env, agent, timelimit=300):
    """Run one episode under the given condition

    Args:
      env (Environment): Environment to run
      agent (Agent): Agent to run
      timelimit (int): Time limit of one episode in second
    """
    outcome = env.reset()
    agent.reset(outcome.observation)

    t0 = time.time()
    rewards, steps = 0, 0
    while not outcome.terminal:
        action = agent.act()
        outcome = env.step(action)

        rewards += outcome.reward
        steps += 1

        agent.observe(action, outcome)

        elapsed = time.time() - t0
        if elapsed > timelimit:
            _LG.info('  Reached time limit')
    return rewards, steps


def run_episodes(env, agent, episodes=30, timelimit=300):
    rewards, steps = [], []
    _LG.info('  Running {} Episodes'.format(episodes))
    for i in range(episodes):
        r, s = run_single_episode(env, agent, timelimit)
        _LG.info('  Ep {}: {} ({} steps)'.format(i+1, r, s))
        rewards.append(r)
        steps.append(s)
    return rewards, steps


def main():
    args = parse_command_line_args()

    files = get_parameter_files(args.input_dir, args.prefix)
    env = load_env(args.env)
    agent = load_agent(args.agent)

    agent.init(env)
    writer = SummaryWriter(args.output_dir)
    if agent.session.graph:
        writer.add_graph(agent.session.graph)
    writer.register_stats(['Reward', 'Steps'])

    for ite, f in files:
        _LG.info('*** Evaluating {}'.format(f))
        agent.session.load_from_file(f)
        rewards, steps = run_episodes(
            env, agent, episodes=args.episodes, timelimit=args.timelimit)
        _LG.info('Average rewards: {}'.format(sum(rewards) / len(rewards)))
        _LG.info('Average steps: {}'.format(sum(steps) / len(steps)))
        writer.summarize_stats(ite, {'Rewards': rewards, 'Steps': steps})

if __name__ == '__main__':
    main()