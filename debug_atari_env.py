import logging
from argparse import ArgumentParser as AP

import numpy as np

from luchador.env import ALEEnvironment

ap = AP()
ap.add_argument('--rom', default='breakout')
ap.add_argument('--display_screen', '-screen', action='store_true')
ap.add_argument('--sound', action='store_true')
ap.add_argument('--record_screen_path')
args = ap.parse_args()

env = ALEEnvironment(
    args.rom,
    display_screen=args.display_screen, sound=args.sound,
    record_screen_path=args.record_screen_path)

logger = logging.getLogger('luchador')

n_actions = env.n_actions
for episode in range(10):
    total_reward = 0.0
    terminal = False
    while not terminal:
        a = np.random.randint(n_actions)
        reward, screen, terminal, info = env.step(a)
        total_reward += reward
    frame_number = env.ale.getFrameNumber()
    frame_number_ep = env.ale.getEpisodeFrameNumber()
    env.reset()

    logger.info('Episode {}: Score: {}'.format(episode, total_reward))
    logger.info('Frame Number: {} / {}'.format(frame_number_ep, frame_number))