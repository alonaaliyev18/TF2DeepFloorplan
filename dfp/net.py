import argparse
import os
from typing import Tuple

import numpy as np
import tensorflow as tf
from tensorflow.keras.applications.vgg16 import VGG16
from tensorflow.keras.models import Model

# import pdb


os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"

# print('Is gpu available: ',tf.test.is_gpu_available());


def conv2d(
    dim: int,
    size: int = 3,
    stride: int = 1,
    rate: int = 1,
    pad: str = "same",
    act: str = "relu",
) -> tf.keras.Sequential:
    result = tf.keras.Sequential()
    result.add(
        tf.keras.layers.Conv2D(
            dim, size, strides=stride, padding=pad, dilation_rate=rate
        )
    )
    if act == "leaky":
        result.add(tf.keras.layers.LeakyReLU())
    elif act == "relu":
        result.add(tf.keras.layers.ReLU())
    return result


def max_pool2d(
    size: int = 2, stride: int = 2, pad: str = "valid"
) -> tf.keras.Sequential:
    result = tf.keras.Sequential()
    result.add(
        tf.keras.layers.MaxPool2D(pool_size=size, strides=stride, padding=pad)
    )
    return result


def upconv2d(
    dim: int,
    size: int = 4,
    stride: int = 2,
    pad: str = "same",
    act: str = "relu",
) -> tf.keras.Sequential:
    result = tf.keras.Sequential() #creating a sequential model
    result.add(
        tf.keras.layers.Conv2DTranspose(dim, size, strides=stride, padding=pad)
    )
    if act == "relu":
        result.add(tf.keras.layers.ReLU())
    return result


def up_bilinear(dim: int) -> tf.keras.Sequential:
    result = tf.keras.Sequential()
    result.add(conv2d(dim, size=1, act="linear"))
    return result


class deepfloorplanModel(Model):
    def __init__(self, config: argparse.Namespace = None):
        """figure 4"""
        super(deepfloorplanModel, self).__init__()
        self._vgg16init()

        dimlist = [256, 128, 64, 32]
        """figure 4 - room boundary  features (input) - VGG for room boundary features"""
        #TODO can update to resnet here

        # room boundary pixels
        self.rbpups = [upconv2d(dim=d, act="linear") for d in dimlist]  # upsampling convolution linear layer that changes from 512*512 to 512*512*256
        self.rbpcv1 = [conv2d(dim=d, act="linear") for d in dimlist]     # list of 2D convolution, # layers =  256, 128 ,64, 32 linear
        self.rbpcv2 = [conv2d(dim=d) for d in dimlist] #list of 2D convolutinal layers reLU activation
        self.rbpfinal = up_bilinear(3) #bilinear upsameling - output depth is 3

        """ figure 4 - room type features VGG for room type features"""
        # room type prediction (rtp)
        self.rtpups = [upconv2d(dim=d, act="linear") for d in dimlist] # upsampling convolution linear layer that changes from 512*512 to 512*512*256
        self.rtpcv1 = [conv2d(dim=d, act="linear") for d in dimlist]  # list of 2D convolution, # layers =  256, 128 ,64, 32 linear
        self.rtpcv2 = [conv2d(dim=d) for d in dimlist] #list of 2D convolutinal layers reLU activation

        # attention map
        """figure 4 in article - attention weights"""
        # An attention map is a visualization to highlight the most relevant regions or parts of an input data instance
        self.atts1 = [conv2d(dim=dimlist[i]) for i in range(len(dimlist))] # list of 2D convolution, # layers =  256, 128 ,64, 32 RELU
        self.atts2 = [conv2d(dim=dimlist[i]) for i in range(len(dimlist))] # list of 2D convolution, # layers =  256, 128 ,64, 32 Relu
        self.atts3 = [
            conv2d(dim=1, size=1, act="sigmoid") for i in range(len(dimlist)) # list of 2D convolution, # layers =  256, 128 ,64, 32 sigmoid
        ]

        # reduce the tensor depth
        self.xs1 = [conv2d(dim=d) for d in dimlist] # convolutional layers with output depth [256, 128, 64, 32] Relu
        self.xs2 = [conv2d(dim=1, size=1, act="linear") for d in dimlist] # convolution layers with output depth 1

        # context conv2d
        dak = [9, 17, 33, 65]  # kernel_shape=[h,v,inc,outc]

        """figure 4 in article - direction aware weights """
        # horizontal
        self.hs = [self.constant_kernel((d, 1, 1, 1)) for d in dak] #shapes for kernel - horizontal
        self.hf = [
            tf.keras.layers.Conv2D(
                1, # output depth
                [dak[i], 1], #size
                strides=1,
                padding="same",
                trainable=False, #weights not changing
                use_bias=False,
                weights=[self.hs[i]],
            )
            for i in range(len(dak))
        ] # creating list of convolution layers with the kernels for weights

        # vertical
        # same as horizontal but vertical
        self.vs = [self.constant_kernel((1, d, 1, 1)) for d in dak]
        self.vf = [
            tf.keras.layers.Conv2D(
                1,
                [1, dak[i]],
                strides=1,
                padding="same",
                trainable=False,
                use_bias=False,
                weights=[self.vs[i]],
            )
            for i in range(len(dak))
        ]

        # diagonal
        self.ds = [self.constant_kernel((d, d, 1, 1), diag=True) for d in dak]
        self.df = [
            tf.keras.layers.Conv2D(
                1,
                dak[i],
                strides=1,
                padding="same",
                trainable=False,
                use_bias=False,
                weights=[self.ds[i]],
            )
            for i in range(len(dak))
        ]

        # diagonal flip
        self.dfs = [
            self.constant_kernel((d, d, 1, 1), diag=True, flip=True)
            for d in dak
        ]
        self.dff = [
            tf.keras.layers.Conv2D(
                1,
                dak[i],
                strides=1,
                padding="same",
                trainable=False,
                use_bias=False,
                weights=[self.dfs[i]],
            )
            for i in range(len(dak))
        ]

        # expand dim
        self.ed = [conv2d(dim=d, size=1, act="linear") for d in dimlist]
        # learn rich feature
        self.lrf = [conv2d(dim=d) for d in dimlist]
        # final
        self.rtpfinal = up_bilinear(9)

    def _vgg16init(self):
        """ uses existing vgg that is pre-trained on image net data set and is not trainable (frozen) that extracts features from the input"""
        """ output shape: 16 * 16 * 512 """
        self.vgg16 = VGG16(
            weights="imagenet", include_top=False, input_shape=(512, 512, 3)
        )
        for layer in self.vgg16.layers:
            layer.trainable = False


    def constant_kernel(
        self,
        shape: Tuple[int, int, int, int],
        val: int = 1,
        diag: bool = False,
        flip: bool = False,
    ) -> np.ndarray:
        k = np.array([]).astype(int)
        if not diag:
            k = val * np.ones(shape)
        else:
            w = np.eye(shape[0], shape[1])
            if flip:
                w = w.reshape((shape[0], shape[1], 1))
                w = np.flip(w, 1)
            k = w.reshape(shape)
        return k

    def non_local_context(
        self, t1: tf.Tensor, t2: tf.Tensor, idx: int, stride: int = 4
    ) -> tf.Tensor:
        """figure 4 - room type decoder learns the contextual features for predicting the room type pixels"""

        N, H, W, C = t1.shape.as_list()  # batch size, height, width and channels
        hs = H // stride if (H // stride) > 1 else (stride - 1)  # height output dimension
        vs = W // stride if (W // stride) > 1 else (stride - 1)  # width output dimension
        hs = hs if (hs % 2 != 0) else hs + 1
        vs = hs if (vs % 2 != 0) else vs + 1
        a = t1
        x = t2

        """apply attention map on te room boundary layer tensor"""
        a = self.atts1[idx](a)
        a = self.atts2[idx](a)
        a = self.atts3[idx](a)
        a = tf.keras.activations.sigmoid(a)  # moves the range to between 0 and 1

        """apply on the room type layer features"""
        x = self.xs1[idx](x)
        x = self.xs2[idx](x)

        x = a * x  # takes the interesting parts of x

        """apply direction aware kernels"""
        h = self.hf[idx](x)
        v = self.vf[idx](x)
        d = self.df[idx](x)
        f = self.dff[idx](x)

        """multiply attention map with the sum of the kernels results"""
        c1 = a * (h + v + d + f)
        c1 = self.ed[idx](c1)  # expend conv

        features = tf.concat([t2, c1], axis=3)  #adds to the depth
        out = self.lrf[idx](features)  # cnn on the spatial contexture
        return out

    def call(self, x: tf.Tensor) -> Tuple[tf.Tensor, tf.Tensor]:
        features = []
        feature = x
        # TODO: switch to resnet here (try)
        for layer in self.vgg16.layers:
            feature = layer(feature)  # apply layer on the features and update it
            if layer.name.find("pool") != -1:  # not adding pooling layers (reduces the number of parameters)
                features.append(feature)
        x = feature
        features = features[::-1]
        featuresrbp = []
        # room boundary decoder
        for i in range(len(self.rbpups)):
            x = self.rbpups[i](x) + self.rbpcv1[i](features[i + 1])
            x = self.rbpcv2[i](x)
            featuresrbp.append(x)
        logits_cw = tf.keras.backend.resize_images(
            self.rbpfinal(x), 2, 2, "channels_last"
        )  # upsampleing (resize image with 2 factor to width and height
        x = feature
        for i in range(len(self.rtpups)):
            x = self.rtpups[i](x) + self.rtpcv1[i](features[i + 1])
            x = self.rtpcv2[i](x)
            x = self.non_local_context(featuresrbp[i], x, i) # use contextual data  from the room boundary matching layer
        logits_r = tf.keras.backend.resize_images(
            self.rtpfinal(x), 2, 2, "channels_last"
        ) # upsampleing (resize image with 2 factor to width and height
        return logits_r, logits_cw
