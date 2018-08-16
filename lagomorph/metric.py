"""
Fluid and other LDDMM metrics
"""
import skcuda.fft
from pycuda import gpuarray, cumath
from pycuda.autoinit import context
import numpy as np

import math

from . import metric_cuda
from .memory import alloc
from .dtypes import dtype2precision

class FluidMetric(object):
    def __init__(self, shape, alpha, beta, gamma, precision='single'):
        """
        This kernel is the Green's function for:

            L'L = - alpha nabla^2 - beta grad div + gamma

        the most commonly used kernel in LDDMM (cf. Christensen et al 1994 or
        Jacob Hinkle's PhD Thesis 2013)

        The shape argument is the size of a velocity or momentum, in NCWHD order
        """
        self.shape = shape
        self.complexshape = list(shape)
        self.complexshape[-1] = self.complexshape[-1]//2+1
        self.complexshape = tuple(self.complexshape)
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.gamma = float(gamma)
        if gamma <= 4*alpha + 2*beta and False:
            print("WARNING: ill-conditioned kernel. gamma <= "
                f"4*alpha + 2*beta = {4*alpha + 2*beta}")
        self.dim = len(shape)-2
        if self.dim != 2 and self.dim != 3:
            raise Exception(f"Invalid dimension: {self.dim}")
        self.precision = precision
        if precision == 'single':
            self.dtype = np.float32
            self.complex_dtype = np.complex64
        elif precision == 'double':
            self.dtype = np.float64
            self.complex_dtype = np.complex128
        else:
            raise Exception(f"Unsupported precision: {precision}")
        # initialize memory for out of place fft
        self.Fv = gpuarray.empty(shape=self.complexshape, allocator=alloc,
                dtype=self.complex_dtype, order='C')
        # initialize lookup tables and send them up to the gpu
        self.initialize_luts()
        # fft plan
        self.fftplan = skcuda.fft.Plan(self.shape[2:], self.dtype, self.complex_dtype, batch=shape[0]*shape[1])
        self.ifftplan = skcuda.fft.Plan(self.shape[2:], self.complex_dtype, self.dtype, batch=shape[0]*shape[1])
    def initialize_luts(self):
        """
        Fill out lookup tables used in Fourier kernel. This amounts to just
        precomputing the sine and cosine (period N_d) for each dimension.
        """
        self.luts = {'cos': [], 'sin': []}
        for (Nf,N) in zip(self.complexshape[2:], self.shape[2:]):
            self.luts['cos'].append(gpuarray.to_gpu(
                np.require((1.-np.cos(2*np.pi*np.arange(N, dtype=self.dtype)/N)),
                    requirements='C'), allocator=alloc))
            self.luts['sin'].append(gpuarray.to_gpu(
                np.require(np.sin(2.*np.pi*np.arange(N, dtype=self.dtype)/N),
                    requirements='C'), allocator=alloc))
    def operator_fourier(self, Fm, inverse=False):
        # call the appropriate cuda kernel here
        block = (32,32,1)
        grid = (math.ceil(self.complexshape[2]/block[0]), math.ceil(self.complexshape[3]/block[1]), 1)
        if self.dim == 2:
            if inverse:
                f = metric_cuda.inverse_operator_2d
            else:
                f = metric_cuda.forward_operator_2d
            f(Fm,
                self.luts['cos'][0], self.luts['sin'][0],
                self.luts['cos'][1], self.luts['sin'][1],
                self.alpha, self.beta, self.gamma,
                self.complexshape[0], self.complexshape[2], self.complexshape[3],
                0, 0,
                block=block, grid=grid,
                precision=self.precision)
        elif self.dim == 3:
            raise NotImplementedError("not implemented yet")
    def sharp(self, m, out=None):
        """
        Raise indices, meaning convert a momentum (covector field) to a velocity
        (vector field) by applying the Green's function which smooths the
        momentum.
        https://en.wikipedia.org/wiki/Musical_isomorphism
        """
        assert m.flags.c_contiguous, "Momentum array must be contiguous"
        assert self.Fv.flags.c_contiguous, "Fv must be contiguous"
        if out is None:
            out = gpuarray.empty_like(m)
        skcuda.fft.fft(m, self.Fv, self.fftplan, scale=True)
        self.operator_fourier(self.Fv, inverse=True)
        skcuda.fft.ifft(self.Fv, out, self.ifftplan)
        return out
    def flat(self, m, out=None):
        """
        Lower indices, meaning convert a vector field to a covector field
        (a momentum)
        https://en.wikipedia.org/wiki/Musical_isomorphism
        """
        assert m.flags.c_contiguous, "Momentum array must be contiguous"
        assert self.Fv.flags.c_contiguous, "Fv must be contiguous"
        if out is None:
            out = gpuarray.empty_like(m)
        skcuda.fft.fft(m.astype(self.dtype), self.Fv, self.fftplan)
        self.operator_fourier(self.Fv, inverse=False)
        skcuda.fft.ifft(self.Fv, out, self.ifftplan, scale=True)
        return out
