"""Module for building neural Q learning network"""
from __future__ import division
from __future__ import absolute_import

import logging
from collections import OrderedDict

import numpy as np

import luchador.util
from luchador import nn

_LG = logging.getLogger(__name__)

__all__ = ['DeepQLearning', 'DoubleDeepQLearning']


def _validate_q_learning_config(
        min_reward=None, max_reward=None,
        min_delta=None, max_delta=None, **_):
    if (min_reward and not max_reward) or (max_reward and not min_reward):
        raise ValueError(
            'When clipping reward, both `min_reward` '
            'and `max_reward` must be provided.')
    if (min_delta and not max_delta) or (max_delta and not min_delta):
        raise ValueError(
            'When clipping reward, both `min_delta` '
            'and `max_delta` must be provided.')


def _make_model(model_def, scope):
    with nn.variable_scope(scope):
        model = nn.make_model(model_def)
        state = model.input
        action_value = model.output
    return model, state, action_value


def _build_sync_op(src_model, tgt_model, scope):
    with nn.variable_scope(scope):
        src_vars = src_model.get_parameter_variables()
        tgt_vars = tgt_model.get_parameter_variables()
        return nn.build_sync_op(src_vars, tgt_vars, name='sync')


class DeepQLearning(luchador.util.StoreMixin, object):
    """Implement Neural Network part of DQN [1]_:

    Parameters
    ----------
    q_learning_config : dict
        Configuration for building target Q value.

        discout_rate : float
            Discount rate for computing future reward. Valid value range is
            (0.0, 1.0)
        scale_reward : number or None
            When given, reward is divided by this number before applying
            min/max threashold
        min_reward : number or None
            When given, clip reward after scaling.
        max_reward : number or None
            See `min_reward`.

    cost_config : dict
        Configuration for defining error between predicted Q and target Q

        name: str
            The name of cost class. See :py:mod:`luchador.nn.base.cost`
            for the list of available costs.
        args : dict
            Configuration for the cost class

    optimizer_config : dict
        Configuration for optimizer

        name: str
            The name of cost class. See :py:mod:`luchador.nn.base.optimizer`
            for the list of available classes.
        args : dict
            Configuration for the optimizer class

    clip_grad: dict
        If given, gradient is clipped.

        min_val
            Minimum value
        max_val
            Maximum value

    References
    ----------
    .. [1] Mnih, V et. al (2015)
        Human-level control through deep reinforcement learning
        https://storage.googleapis.com/deepmind-media/dqn/DQNNaturePaper.pdf
    """
    # pylint: disable=too-many-instance-attributes
    def __init__(
            self, q_learning_config, cost_config, optimizer_config, clip_grad):
        self._store_args(
            q_learning_config=q_learning_config,
            cost_config=cost_config,
            optimizer_config=optimizer_config,
            clip_grad=clip_grad,
        )
        self.vars = None
        self.models = None
        self.ops = None
        self.optimizer = None
        self.session = None

    def _validate_args(self, q_learning_config=None, clip_grad=None, **_):
        if q_learning_config is not None:
            _validate_q_learning_config(**q_learning_config)

        if clip_grad:
            if not ('min_value' in clip_grad and 'max_value' in clip_grad):
                raise ValueError(
                    '`min_value` and `max_value` must be given in `clip_grad`')

    def build(self, model_def, initial_parameter):
        """Build computation graph (error and sync ops) for Q learning

        Parameters
        ----------
        n_actions: int
            The number of available actions in the environment.
        """
        # pylint: disable=too-many-locals
        model_0, state_0, action_value_0 = _make_model(model_def, 'pre_trans')
        model_1, state_1, action_value_1 = _make_model(model_def, 'post_trans')
        sync_op = _build_sync_op(model_0, model_1, 'sync')

        with nn.variable_scope('target_q_value'):
            reward = nn.Input(shape=(None,), name='rewards')
            terminal = nn.Input(shape=(None,), name='terminal')
            target_q, post_q = self._build_target_q_value(
                action_value_1, reward, terminal)

        with nn.variable_scope('error'):
            action_0 = nn.Input(
                shape=(None,), dtype='int32', name='action_0')
            error = self._build_error(target_q, action_value_0, action_0)

        self._init_optimizer()
        optimize_op = self._build_optimize_op(
            loss=error,
            params=model_0.get_parameter_variables())
        self._init_session(initial_parameter)

        self.models = {
            'model_0': model_0,
            'model_1': model_1,
        }
        self.vars = {
            'state_0': state_0,
            'state_1': state_1,
            'action_value_0': action_value_0,
            'action_value_1': action_value_1,
            'action_0': action_0,
            'reward': reward,
            'terminal': terminal,
            'post_q': post_q,
            'target_q': target_q,
            'error': error,
        }
        self.ops = {
            'sync': sync_op,
            'optimize': optimize_op,
        }

    def _build_target_q_value(self, action_value_1, reward, terminal):
        config = self.args['q_learning_config']
        # Clip rewrads
        if 'scale_reward' in config:
            reward = reward / config['scale_reward']
        if 'min_reward' in config and 'max_reward' in config:
            min_val, max_val = config['min_reward'], config['max_reward']
            reward = reward.clip(min_value=min_val, max_value=max_val)

        # Build Target Q
        post_q = action_value_1.max(axis=1)
        discounted_q = post_q * config['discount_rate']
        target_q = reward + (1.0 - terminal) * discounted_q

        n_actions = action_value_1.shape[1]
        target_q = target_q.reshape([-1, 1]).tile([1, n_actions])
        return target_q, post_q

    def _build_error(self, target_q, action_value_0, action):
        n_actions = action_value_0.shape[1]
        config = self.args['cost_config']
        cost = nn.get_cost(config['typename'])(
            elementwise=True, **config.get('args', {}))
        error = cost(target_q, action_value_0)
        mask = nn.one_hot(action, n_classes=n_actions, dtype=error.dtype)
        return (mask * error).mean()

    def _build_optimize_op(self, loss, params):
        grads_and_vars = self.optimizer.compute_gradients(
            loss=loss, wrt=params)
        # Remove untrainables
        grads_and_vars = [g_v for g_v in grads_and_vars if g_v[0] is not None]
        # Clip gradients
        if self.args.get('clip_grad'):
            max_ = self.args['clip_grad']['max_value']
            min_ = self.args['clip_grad']['min_value']
            grads_and_vars = [
                (g_v.clip(max_value=max_, min_value=min_), var)
                for g_v, var in grads_and_vars
            ]
        return self.optimizer.apply_gradients(grads_and_vars)

    ###########################################################################
    def _init_optimizer(self):
        cfg = self.args['optimizer_config']
        self.optimizer = nn.get_optimizer(cfg['typename'])(**cfg['args'])

    def _init_session(self, initial_parameter=None):
        self.session = nn.Session()
        if initial_parameter:
            _LG.info('Loading parameters from %s', initial_parameter)
            self.session.load_from_file(initial_parameter)
        else:
            self.session.initialize()

    ###########################################################################
    def predict_action_value(self, state):
        """Predict action values

        Parameters
        ----------
        state : NumPy ND Array
            Environment state

        Returns
        -------
        NumPy ND Array
            Action values
        """
        return self.session.run(
            outputs=self.vars['action_value_0'],
            inputs={self.vars['state_0']: state},
            name='action_value0',
        )

    def sync_network(self):
        """Synchronize parameters of model_1 with those of model_0"""
        self.session.run(updates=self.ops['sync'], name='sync')

    def train(self, state_0, action_0, reward, state_1, terminal):
        """Train model network

        Parameters
        ----------
        state_0 : NumPy ND Array
            Environment states before taking actions

        action_0 : NumPy ND Array
            Actions taken in state_0

        reward : NumPy ND Array
            Rewards obtained by taking the action_0.

        state_1 : NumPy ND Array
            Environment states after action_0 are taken

        terminal : NumPy ND Array
            Flags for marking corresponding states in state_1 are
            terminal states.

        Returns
        -------
        NumPy ND Array
            Mean error between Q prediction and target Q
        """
        updates = self.models['model_0'].get_update_operations()
        updates += [self.ops['optimize']]
        return self.session.run(
            outputs=self.vars['error'],
            inputs={
                self.vars['state_0']: state_0,
                self.vars['action_0']: action_0,
                self.vars['reward']: reward,
                self.vars['state_1']: state_1,
                self.vars['terminal']: terminal,
            },
            updates=updates,
            name='minibatch_training',
        )

    ###########################################################################
    def fetch_all_parameters(self):
        """Fetch network parameters and optimizer parameters for saving"""
        params = (
            self.models['model_0'].get_parameter_variables() +
            self.optimizer.get_parameter_variables()
        )
        params_val = self.session.run(outputs=params, name='save_params')
        return OrderedDict([
            (var.name, val) for var, val in zip(params, params_val)
        ])

    ###########################################################################
    def fetch_layer_params(self):
        """Fetch paramters of each layer"""
        params = self.models['model_0'].get_parameter_variables()
        params_vals = self.session.run(outputs=params, name='model_0_params')
        return {
            '/'.join(v.name.split('/')[1:]): val
            for v, val in zip(params, params_vals)
        }

    def fetch_layer_outputs(self, state):
        """Fetch outputs from each layer

        Parameters
        ----------
        state : NumPy ND Array
            Input to model_0 (pre-transition model)
        """
        outputs = self.models['model_0'].get_output_tensors()
        output_vals = self.session.run(
            outputs=outputs,
            inputs={self.vars['state_0']: state},
            name='model_0_outputs'
        )
        return {
            '/'.join(v.name.split('/')[1:]): val
            for v, val in zip(outputs, output_vals)
        }


class DoubleDeepQLearning(DeepQLearning):
    """Implement Neural Network part of Double DQN [1]_:

    References
    ----------
    .. [1] Hasselt, H et. al (2015)
        Deep Reinforcement Learning with Double Q-learning
        https://arxiv.org/abs/1509.06461
    """
    def train(self, state_0, action_0, reward, state_1, terminal):
        """Train model network

        Parameters
        ----------
        state_0 : NumPy ND Array
            Environment states before taking actions

        action_0 : NumPy ND Array
            Actions taken in state_0

        reward : NumPy ND Array
            Rewards obtained by taking the action_0.

        state_1 : NumPy ND Array
            Environment states after action_0 are taken

        terminal : NumPy ND Array
            Flags for marking corresponding states in state_1 are
            terminal states.

        Returns
        -------
        NumPy ND Array
            Mean error between Q prediction and target Q
        """
        # Find the best action after state_1 by feeding state_1 to model_0
        action_value_1_0, action_value_1 = self.session.run(
            outputs=[
                self.vars['action_value_0'],
                self.vars['action_value_1'],
            ],
            inputs={
                self.vars['state_0']: state_1,
                self.vars['state_1']: state_1,
            },
            name='fetch_action',
        )
        post_q = action_value_1[
            [i for i in range(action_value_1.shape[0])],
            np.argmax(action_value_1_0, axis=1)
        ]
        updates = self.models['model_0'].get_update_operations()
        updates += [self.ops['optimize']]
        return self.session.run(
            outputs=self.vars['error'],
            inputs={
                self.vars['state_0']: state_0,
                self.vars['action_0']: action_0,
                self.vars['post_q']: post_q,
                self.vars['reward']: reward,
                self.vars['terminal']: terminal,
            },
            updates=updates,
            name='minibatch_training',
        )
