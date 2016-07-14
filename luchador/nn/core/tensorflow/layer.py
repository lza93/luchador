from __future__ import division
from __future__ import absolute_import

import logging
import warnings

import tensorflow as tf
from tensorflow.contrib import layers

from ..base import (
    ReLU as BaseReLU,
    Dense as BaseDense,
    Conv2D as BaseConv2D,
    Flatten as BaseFlatten,
    TrueDiv as BaseTrueDiv,
)
from . import config as CFG
from .tensor import Tensor

_LG = logging.getLogger(__name__)

__all__ = ['Dense', 'Conv2D', 'ReLU', 'Flatten', 'TrueDiv']


class Dense(BaseDense):
    def _instantiate_parameter_variables(self, n_inputs):
        b_shape = (self.args['n_nodes'],)
        w_shape = (n_inputs, self.args['n_nodes'])

        given = self.args.get('initializers')
        b0 = given['bias'] if given else tf.constant_initializer(0.1)
        w0 = given['weight'] if given else layers.xavier_initializer()

        b = tf.get_variable(
            name='bias', shape=b_shape, initializer=b0, dtype=CFG.DTYPE)
        W = tf.get_variable(
            name='weight', shape=w_shape, initializer=w0, dtype=CFG.DTYPE)
        self.parameter_variables['weight'] = Tensor(tensor=W)
        self.parameter_variables['bias'] = Tensor(tensor=b)

    def build(self, input):
        _LG.debug('    Building {}: {}'.format(type(self).__name__, self.args))
        if not self.parameter_variables:
            self._instantiate_parameter_variables(input.get_shape()[1])

        params = self.parameter_variables
        prod = tf.matmul(input.tensor, params['weight'].tensor)
        output = tf.add(prod, params['bias'].tensor, name='output')
        return Tensor(tensor=output)


class Conv2D(BaseConv2D):
    def _validate_padding(self, padding):
        if padding not in ['SAME', 'VALID']:
            raise ValueError('`padding` must be either "SAME" or "VALID"')

    def _validate_strides(self, strides):
        if isinstance(strides, int):
            return
        try:
            if (
                    len(strides) in [2, 4] and
                    all(map(lambda s: isinstance(s, int), strides))
            ):
                return
        except Exception:
            pass
        raise ValueError(
            '`strides` must be either int, '
            'tuple of two ints, or tuple of four ints'
        )

    def _validate_args(self, args):
        args['padding'] = args['padding'].upper()
        self._validate_padding(args['padding'])
        self._validate_strides(args['strides'])

    ###########################################################################
    def _get_strides(self):
        s, fmt = self.args['strides'], CFG.CNN_FORMAT
        if isinstance(s, int):
            s = [s] * 2
        if len(s) == 2:
            s = (1, 1, s[0], s[1]) if fmt == 'NCHW' else (1, s[0], s[1], 1)
        return s

    def _get_weight_shape(self, input_shape):
        n_out = self.args['n_filters']
        n_in = input_shape[1] if CFG.CNN_FORMAT == 'NCHW' else input_shape[3]
        height, width = self.args['filter_height'], self.args['filter_width']
        return (height, width, n_in, n_out)

    def _check_filter_shape(self, input_shape, filter_shape):
        flt_h, flt_w = filter_shape[0], filter_shape[1]
        strides = self._get_strides()
        if CFG.CNN_FORMAT == 'NCHW':
            img_h, img_w = input_shape[2], input_shape[3]
            str_h, str_w = strides[2], strides[3]
        else:
            img_h, img_w = input_shape[1], input_shape[2]
            str_h, str_w = strides[1], strides[2]
        if self.args['padding'] == 'VALID':
            warn_w = bool((img_w - flt_w) % str_w)
            warn_h = bool((img_h - flt_h) % str_h)
        else:
            warn_w = bool((img_w - 1) % str_w)
            warn_h = bool((img_h - 1) % str_h)
        if warn_w:
            warnings.warn(
                'Convolution op will not cover the right side of the input.'
                'Check the width configuration of filter and stride.',
                RuntimeWarning
            )
        if warn_h:
            warnings.warn(
                'Convolution op will not cover the bottom part of the input.'
                'Check the height configuration of filter and stride.',
                RuntimeWarning
            )

    def _instantiate_parameter_variables(self, input_shape):
        _LG.debug('    Input shape: {}'.format(input_shape))
        b_shape = (self.args['n_filters'],)
        w_shape = self._get_weight_shape(input_shape)

        self._check_filter_shape(input_shape, w_shape)

        given = self.args.get('initializers')
        b0 = given['bias'] if given else tf.constant_initializer(0.1)
        w0 = given['weight'] if given else layers.xavier_initializer_conv2d()

        b = tf.get_variable(
            name='bias', shape=b_shape, initializer=b0, dtype=CFG.DTYPE)
        w = tf.get_variable(
            name='weight', shape=w_shape, initializer=w0, dtype=CFG.DTYPE)
        self.parameter_variables['weight'] = Tensor(tensor=w)
        self.parameter_variables['bias'] = Tensor(tensor=b)

    def build(self, input):
        _LG.debug('    Building {}: {}'.format(type(self).__name__, self.args))
        if not self.parameter_variables:
            self._instantiate_parameter_variables(input.get_shape())

        strides = self._get_strides()
        params = self.parameter_variables
        name = self.args['kwargs'].get('name')
        cudnn = self.args['kwargs'].get('use_cudnn_on_gpu', True)
        conv = tf.nn.conv2d(
            input.tensor, params['weight'].tensor, strides=strides,
            padding=self.args['padding'], use_cudnn_on_gpu=cudnn,
            data_format=CFG.CNN_FORMAT, name=name)
        output = tf.nn.bias_add(conv, params['bias'].tensor,
                                data_format=CFG.CNN_FORMAT, name='output')
        return Tensor(output)


class ReLU(BaseReLU):
    def build(self, input):
        _LG.debug('    Building {}: {}'.format(type(self).__name__, self.args))
        output = tf.nn.relu(input.tensor, 'ouptut')
        return Tensor(output)


class Flatten(BaseFlatten):
    def build(self, input):
        _LG.debug('    Building {}: {}'.format(type(self).__name__, self.args))
        in_shape = input.get_shape()
        n_nodes = reduce(lambda prod, dim: prod*dim, in_shape[1:], 1)
        out_shape = (-1, n_nodes)
        output = tf.reshape(input.tensor, out_shape, 'output')
        return Tensor(output)


class TrueDiv(BaseTrueDiv):
    def _instantiate_denominator(self):
        dtype = self.args['dtype'] or CFG.DTYPE
        self.denom = tf.constant(
            self.args['denom'], dtype=dtype, name='denominator')

    def build(self, input):
        _LG.debug('    Building {}: {}'.format(type(self).__name__, self.args))
        if self.denom is None:
            self._instantiate_denominator()
        output = tf.truediv(input.tensor, self.denom, 'ouptut')
        return Tensor(output)