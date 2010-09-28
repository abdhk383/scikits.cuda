#!/usr/bin/env python

"""
PyCUDA-based FFT functions.
"""

import pycuda.gpuarray as gpuarray
import numpy as np

import cufft

class Plan:
    """
    CUFFT plan class.
    
    This class represents an FFT plan for CUFFT.

    Parameters
    ----------
    shape : tuple of ints
        Transform size. Must contain no more than 3 elements.
    in_dtype : { numpy.float32, numpy.float64, numpy.complex64, numpy.complex128 }
        Type of input data.
    out_dtype : { numpy.float32, numpy.float64, numpy.complex64, numpy.complex128 }
        Type of output data.

    Notes
    -----
    Transform plan configurations of dimensions higher than 3 are
    supported by CUFFT, but have not yet been exposed in this
    function.
    
    """
    
    def __init__(self, shape, in_dtype, out_dtype):

        if np.isscalar(shape):
            self.shape = (shape, )
        else:            
            self.shape = shape

        self.in_dtype = in_dtype
        self.out_dtype = out_dtype
        
        # Determine type of transformation:
        if in_dtype == np.float32 and out_dtype == np.complex64:
            self.fft_type = cufft.CUFFT_R2C
            self.fft_func = cufft.cufftExecR2C
        elif in_dtype == np.complex64 and out_dtype == np.float32:
            self.fft_type = cufft.CUFFT_C2R
            self.fft_func = cufft.cufftExecC2R
        elif in_dtype == np.complex64 and out_dtype == np.complex64:
            self.fft_type = cufft.CUFFT_C2C
            self.fft_func = cufft.cufftExecC2C
        elif in_dtype == np.float64 and out_dtype == np.complex128:
            self.fft_type = cufft.CUFFT_D2Z
            self.fft_func = cufft.cufftExecD2Z
        elif in_dtype == np.complex128 and out_dtype == np.float64:
            self.fft_type = cufft.CUFFT_Z2D
            self.fft_func = cufft.cufftExecZ2D
        elif in_dtype == np.complex128 and out_dtype == np.complex128:
            self.fft_type = cufft.CUFFT_Z2Z
            self.fft_func = cufft.cufftExecZ2Z
        else:
            raise ValueError('unsupported input/output type combination')

        # Set up plan:
        if len(self.shape) == 1:
            self.handle = cufft.cufftPlan1d(self.shape[0],
                                            self.fft_type, 1)
        elif len(self.shape) == 2:
            self.handle = cufft.cufftPlan2d(self.shape[0], self.shape[1],
                                            self.fft_type)
        elif len(self.shape) == 3:
            self.handle = cufft.cufftPlan3d(self.shape[0], self.shape[1],
                                            self.shape[2], self.fft_type)
        else:
            raise ValueError('transforms of dimension > 3 not yet supported')
                                            
    def __del__(self):
        cufft.cufftDestroy(self.handle)
          
def _fft(x_gpu, y_gpu, plan, direction, scale=None):
    """
    Fast Fourier Transform.

    Parameters
    ----------
    x_gpu : pycuda.gpuarray.GPUArray
        Input array.
    y_gpu : pycuda.gpuarray.GPUArray
        Output array.
    plan : Plan
        FFT plan.
    direction : { cufft.CUFFT_FORWARD, cufft.CUFFT_INVERSE }
        Transform direction. Only affects in-place transforms.
    
    Optional Parameters
    -------------------
    scale : int or float
        Scale the values in the output array by dividing them by this value.
    
    Notes
    -----
    This function should not be called directly.
    
    """

    if (x_gpu.gpudata == y_gpu.gpudata) and \
           plan.fft_type not in [cufft.CUFFT_C2C, cufft.CUFFT_Z2Z]:
        raise ValueError('can only compute in-place transform of complex data')

    if direction == cufft.CUFFT_FORWARD and \
           plan.in_dtype in np.sctypes['complex'] and \
           plan.out_dtype in np.sctypes['float']:
        raise ValueError('cannot compute forward complex -> real transform')

    if direction == cufft.CUFFT_INVERSE and \
           plan.in_dtype in np.sctypes['float'] and \
           plan.out_dtype in np.sctypes['complex']:
        raise ValueError('cannot compute inverse real -> complex transform')

    if plan.fft_type in [cufft.CUFFT_C2C, cufft.CUFFT_Z2Z]:
        plan.fft_func(plan.handle, int(x_gpu.gpudata), int(y_gpu.gpudata),
                      direction)
    else:
        plan.fft_func(plan.handle, int(x_gpu.gpudata),
                      int(y_gpu.gpudata))
        
    # Scale the result by dividing it by the number of elements:
    if scale != None:
        y_gpu.gpudata = (y_gpu/np.cast[y_gpu.dtype](scale)).gpudata

def fft(x_gpu, y_gpu, plan, scale=False):
    """
    Fast Fourier Transform.

    Compute the FFT of some data in device memory using the
    specified plan.

    Parameters
    ----------
    x_gpu : pycuda.gpuarray.GPUArray
        Input array.
    y_gpu : pycuda.gpuarray.GPUArray
        FFT of input array.
    plan : Plan
        FFT plan.
    scale : bool, optional
        If True, scale the computed FFT by the number of elements in
        the input array.

    Examples
    --------
    >>> import pycuda.autoinit
    >>> import pycuda.gpuarray as gpuarray
    >>> import numpy as np
    >>> N = 128
    >>> x = np.asarray(np.random.rand(N), np.float32)
    >>> xf = np.fft.fft(x)
    >>> x_gpu = gpuarray.to_gpu(x)
    >>> xf_gpu = gpuarray.empty(N/2+1, np.complex64)
    >>> plan = Plan(x.shape, np.float32, np.complex64)
    >>> fft(x_gpu, xf_gpu, plan)
    >>> np.allclose(xf[0:N/2+1], xf_gpu.get(), atol=1e-6)
    True
    
    Returns
    -------
    y_gpu : pycuda.gpuarray.GPUArray
        Computed FFT.

    Notes
    -----
    For real to complex transformations, this function computes
    N/2+1 non-redundant coefficients of a length-N input signal.
    
    """

    if scale == True:
        return _fft(x_gpu, y_gpu, plan, cufft.CUFFT_FORWARD, x_gpu.size)
    else:
        return _fft(x_gpu, y_gpu, plan, cufft.CUFFT_FORWARD)
    
def ifft(x_gpu, y_gpu, plan, scale=False):
    """
    Inverse Fast Fourier Transform.

    Compute the inverse FFT of some data in device memory using the
    specified plan.

    Parameters
    ----------
    x_gpu : pycuda.gpuarray.GPUArray
        Input array.
    y_gpu : pycuda.gpuarray.GPUArray
        Inverse FFT of input array.
    plan : Plan
        FFT plan.
    scale : bool, optional
        If True, scale the computed inverse FFT by the number of
        elements in the output array.        

    Examples
    --------
    >>> import pycuda.autoinit
    >>> import pycuda.gpuarray as gpuarray
    >>> import numpy as np
    >>> N = 128
    >>> x = np.asarray(np.random.rand(N), np.float32)
    >>> xf = np.asarray(np.fft.fft(x), np.complex64)
    >>> xf_gpu = gpuarray.to_gpu(xf[0:N/2+1])
    >>> x_gpu = gpuarray.empty(N, np.float32)
    >>> plan = Plan(N, np.complex64, np.float32)
    >>> ifft(xf_gpu, x_gpu, plan, True)
    >>> np.allclose(x, x_gpu.get(), atol=1e-6)
    True

    Notes
    -----
    For complex to real transformations, this function assumes the
    input contains N/2+1 non-redundant FFT coefficents of a signal of
    length N.
    
    """

    if scale == True:
        return _fft(x_gpu, y_gpu, plan, cufft.CUFFT_INVERSE, y_gpu.size)
    else:
        return _fft(x_gpu, y_gpu, plan, cufft.CUFFT_INVERSE)

if __name__ == "__main__":
    import doctest
    doctest.testmod()
