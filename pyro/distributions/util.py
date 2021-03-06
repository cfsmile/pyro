from __future__ import absolute_import, division, print_function

import numbers
from contextlib import contextmanager

import torch
import torch.distributions as torch_dist

_VALIDATION_ENABLED = False


def copy_docs_from(source_class, full_text=False):
    """
    Decorator to copy class and method docs from source to destin class.
    """

    def decorator(destin_class):
        # This works only in python 3.3+:
        # if not destin_class.__doc__:
        #     destin_class.__doc__ = source_class.__doc__
        for name in dir(destin_class):
            if name.startswith('_'):
                continue
            destin_attr = getattr(destin_class, name)
            destin_attr = getattr(destin_attr, '__func__', destin_attr)
            source_attr = getattr(source_class, name, None)
            source_doc = getattr(source_attr, '__doc__', None)
            if source_doc and not getattr(destin_attr, '__doc__', None):
                if full_text or source_doc.startswith('See '):
                    destin_doc = source_doc
                else:
                    destin_doc = 'See :meth:`{}.{}.{}`'.format(
                        source_class.__module__, source_class.__name__, name)
                if isinstance(destin_attr, property):
                    # Set docs for object properties.
                    # Since __doc__ is read-only, we need to reset the property
                    # with the updated doc.
                    updated_property = property(destin_attr.fget,
                                                destin_attr.fset,
                                                destin_attr.fdel,
                                                destin_doc)
                    setattr(destin_class, name, updated_property)
                else:
                    destin_attr.__doc__ = destin_doc
        return destin_class

    return decorator


def is_identically_zero(x):
    """
    Check if argument is exactly the number zero. True for the number zero;
    false for other numbers; false for :class:`~torch.Tensor`s.
    """
    return isinstance(x, numbers.Number) and x == 0


def is_identically_one(x):
    """
    Check if argument is exactly the number one. True for the number one;
    false for other numbers; false for :class:`~torch.Tensor`s.
    """
    return isinstance(x, numbers.Number) and x == 1


def broadcast_shape(*shapes, **kwargs):
    """
    Similar to ``np.broadcast()`` but for shapes.
    Equivalent to ``np.broadcast(*map(np.empty, shapes)).shape``.

    :param tuple shapes: shapes of tensors.
    :param bool strict: whether to use extend-but-not-resize broadcasting.
    :returns: broadcasted shape
    :rtype: tuple
    :raises: ValueError
    """
    strict = kwargs.pop('strict', False)
    reversed_shape = []
    for shape in shapes:
        for i, size in enumerate(reversed(shape)):
            if i >= len(reversed_shape):
                reversed_shape.append(size)
            elif reversed_shape[i] == 1 and not strict:
                reversed_shape[i] = size
            elif reversed_shape[i] != size and (size != 1 or strict):
                raise ValueError('shape mismatch: objects cannot be broadcast to a single shape: {}'.format(
                    ' vs '.join(map(str, shapes))))
    return tuple(reversed(reversed_shape))


def sum_rightmost(value, dim):
    """
    Sum out ``dim`` many rightmost dimensions of a given tensor.

    If ``dim`` is 0, no dimensions are summed out.
    If ``dim`` is ``float('inf')``, then all dimensions are summed out.
    If ``dim`` is 1, the rightmost 1 dimension is summed out.
    If ``dim`` is 2, the rightmost two dimensions are summed out.
    If ``dim`` is -1, all but the leftmost 1 dimension is summed out.
    If ``dim`` is -2, all but the leftmost 2 dimensions are summed out.
    etc.

    :param torch.Tensor value: A tensor of ``.dim()`` at least ``dim``.
    :param int dim: The number of rightmost dims to sum out.
    """
    if isinstance(value, numbers.Number):
        return value
    if dim < 0:
        dim += value.dim()
    if dim == 0:
        return value
    if dim >= value.dim():
        return value.sum()
    return value.reshape(value.shape[:-dim] + (-1,)).sum(-1)


def sum_leftmost(value, dim):
    """
    Sum out ``dim`` many leftmost dimensions of a given tensor.

    If ``dim`` is 0, no dimensions are summed out.
    If ``dim`` is ``float('inf')``, then all dimensions are summed out.
    If ``dim`` is 1, the leftmost 1 dimension is summed out.
    If ``dim`` is 2, the leftmost two dimensions are summed out.
    If ``dim`` is -1, all but the rightmost 1 dimension is summed out.
    If ``dim`` is -2, all but the rightmost 2 dimensions are summed out.
    etc.

    Example::

        x = torch.ones(2, 3, 4)
        assert sum_leftmost(x, 1).shape == (3, 4)
        assert sum_leftmost(x, -1).shape == (4,)

    :param torch.Tensor value: A tensor
    :param int dim: Specifies the number of dims to sum out
    """
    if isinstance(value, numbers.Number):
        return value
    if dim < 0:
        dim += value.dim()
    if dim == 0:
        return value
    if dim >= value.dim():
        return value.sum()
    return value.reshape(-1, *value.shape[dim:]).sum(0)


def scale_tensor(tensor, scale):
    """
    Safely scale a tensor, avoiding NANs by assuming::

        inf * 0 = 0 * inf = 0
    """
    # Check for trivial cases.
    if isinstance(tensor, numbers.Number):
        if tensor == 0:
            if isinstance(scale, numbers.Number):
                return 0.0
            return scale.new_zeros(scale.shape)
        if tensor == 1:
            return scale
    if isinstance(scale, numbers.Number):
        if scale == 0:
            if isinstance(tensor, numbers.Number):
                return 0.0
            return tensor.new_zeros(tensor.shape)
        if scale == 1:
            return tensor

    result = tensor * scale

    # avoid NANs
    if not isinstance(scale, numbers.Number):
        result[(scale == 0).expand_as(result)] = 0
    if not isinstance(tensor, numbers.Number):
        result[(tensor == 0).expand_as(result)] = 0

    return result


def torch_sign(value):
    """
    Like :func:`torch.sign`` but also works for numbers.
    """
    if isinstance(value, numbers.Number):
        return (value > 0) - (value < 0)
    return torch.sign(value)


try:
    from torch import logsumexp  # for pytorch 0.4.1 and later
except ImportError:
    def logsumexp(tensor, dim=-1, keepdim=False):
        """
        Numerically stable implementation for the `LogSumExp` operation. The
        summing is done along the dimension specified by ``dim``.

        :param torch.Tensor tensor: Input tensor.
        :param dim: Dimension to be summed out.
        :param keepdim: Whether to retain the dimension
            that is summed out.
        """
        max_val = tensor.max(dim, keepdim=True)[0]
        log_sum_exp = max_val + (tensor - max_val).exp().sum(dim=dim, keepdim=True).log()
        return log_sum_exp if keepdim else log_sum_exp.squeeze(dim)


log_sum_exp = logsumexp  # DEPRECATED


def enable_validation(is_validate):
    global _VALIDATION_ENABLED
    _VALIDATION_ENABLED = is_validate
    torch_dist.Distribution.set_default_validate_args(is_validate)


def is_validation_enabled():
    return _VALIDATION_ENABLED


@contextmanager
def validation_enabled(is_validate=True):
    distribution_validation_status = is_validation_enabled()
    try:
        enable_validation(is_validate)
        yield
    finally:
        enable_validation(distribution_validation_status)
