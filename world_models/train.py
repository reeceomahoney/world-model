import argparse
import os
import pickle

import torch
from tqdm import tqdm

import common
from agent import Agent

# paths
home_path = os.path.dirname(os.path.realpath(__file__))
config_path = home_path + '/config.yaml'

# parse args
parser = argparse.ArgumentParser()
parser.add_argument('--env', type=str, default='raisim')
parser.add_argument('--agent', type=str, default=None)
parser.add_argument('--replay', type=str, default=None)
args = parser.parse_args()

# config and env
config, config_dict = common.init_config(config_path, args.env)
env_driver = common.get_driver(config, config_dict)
print(f'using device: {config.device}')

# agent
obs_dim, act_dim = env_driver.env_info()[:2]
agent = Agent(*env_driver.env_info(), config)
if args.agent is not None:
    agent_state_dict = torch.load(home_path + args.agent, map_location=config.device)
    agent.load_state_dict(agent_state_dict)

# replay buffer
if args.replay is None:
    replay = common.ReplayBuffer(config, {'obs': obs_dim, 'reward': 1, 'cont': 1, 'action': act_dim})
else:
    with open(home_path + args.replay, 'rb') as handle:
        replay = pickle.load(handle)
logger = common.Logger(config, agent, env_driver, replay)

import time
start = time.time()
foo = [{k: torch.randn((100, 100)) for k in ['a', 'b', 'c', 'd']}]


if not config.zero_shot:
    print('prefilling buffer...')
    pbar = tqdm(total=config.prefill)
    obs, h_t, action = env_driver.reset()
    while len(replay) < config.prefill:
        obs, reward, done = env_driver(action)
        h_t, action = agent(h_t, obs)
        replay.store({'obs': obs, 'reward': reward, 'cont': 1 - done, 'action': action})
        if done.any() or env_driver.step >= config.time_limit:
            replay.add_episode()
            obs, h_t, action = env_driver.reset()
        pbar.n = len(replay)
        pbar.refresh()
    replay.add_episode()
    pbar.close()

    print('\npretraining...')
    pbar = tqdm(total=config.pretrain)
    for step in range(config.pretrain):
        info = agent.train_step(step, replay, True)
        pbar.update(1)
    pbar.close()

    should_train = common.Every(config.train_every)
    should_log = common.Every(config.log_every)
    should_eval = common.Every(config.eval_every)

    print('\ntraining...')
    obs, h_t, action = env_driver.reset()
    for step in range(int(config.steps)):
        obs, reward, done = env_driver(action)
        h_t, action = agent(h_t, obs)
        replay.store({'obs': obs, 'reward': reward, 'cont': 1 - done, 'action': action})

        info = agent.train_step(step, replay, should_train(step))
        logger.log(info, step, should_log(step), should_eval(step))

        if done.any() or env_driver.step >= config.time_limit:
            replay.add_episode()
            obs, h_t, action = env_driver.reset()

    for driver in [env_driver, logger.env_driver]:
        driver.close()

if config.zero_shot:
    should_log = common.Every(config.log_every)
    should_eval = common.Every(config.eval_every)

    print('zero-shot training...')
    for step in range(int(config.steps)):
        info = agent.train_step_zero_shot(replay)
        logger.log(info, step, should_log(step), should_eval(step))


# TODO: refactor this into a top level script that calls either dreamer.py or ditto.py
# TODO: add vision
