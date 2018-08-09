"""
Adjoint representation for Diff(R^d)
"""
from pycuda import gpuarray

from .diff import gradient, jacobian_times_vectorfield, divergence
from .deform import interp_def

class AdjRep(object):
    def __init__(self, dim):
        """
        Args:
            dim: integer, either 2 or 3
        """
        self.dim = dim
    def ad(self, v, w):
        """
        This is ad(v,w), the adjoint action of a velocity v on a
        velocity w.

            ad(v,w) = -[v,w] = Dv w - Dw v
        """
        return jacobian_times_vectorfield(v,w) - jacobian_times_vectorfield(w,v)
    def Ad(self, phi, v):
        """
        This is Ad(phi,v), the big adjoint action of a deformation phi on a
        velocity w.

            Ad(phi,v) = (Dphi \circ phi^{-1}) v\circ phi^{-1}

        This is a tricky computation, is not commonly needed in practice and
        will not be implemented until needed.
        """
        raise NotImplementedError("not implemented yet")
    def ad_star(self, v, m):
        """
        This is ad^*(v,m), the coadjoint action of a velocity v on a
        vector momentum m.

            ad^*(v, m) = (Dv)^T m + Dm v + m div v

        where div denotes the divergence of a vector field
        """
        out = jacobian_times_vectorfield(v, m, transpose=True) + jacobian_times_vectorfield(m, v)     
        dv = divergence(v)
        out += m*dv.expand_dims(1)
        return out
    def Ad_star(self, phi, m):
        """
        This is Ad^*(phi,m), the big coadjoint action of a deformation phi on a
        vector momentum m. The formula for this is

            Ad^*(phi,m)(x) = (D phi(x)) m(phi(x))

        where D denotes the Jacobian matrix.
        """
        # First interpolate m
        mphi = interp_def(m, phi)
        return jacobian_times_vectorfield(phi, mphi)
    # dagger versions of the above coadjoint operators
    # The dagger indicates that instead of a _dual_ action, the _adjoint_ action
    # under a metric. These are performed by flatting, applying to dual action,
    # then sharping.
    def ad_dagger(self, x, y, metric):
        return metric.sharp(self.ad_star(x, metric.flat(y)))
    def Ad_dagger(self, phi, y, metric):
        return metric.sharp(self.Ad_star(phi, metric.flat(y)))
    # The sym operator is a negative symmetrized ad_dagger, and is important for
    # computing reduced Jacobi fields.
    # cf. Bullo 1995 or Hinkle 2015 (PhD thesis)
    def sym(self, x, y, metric):
        return -(self.ad_dagger(x, y, metric) + self.ad_dagger(y, x, metric))
    def sym_dagger(self, x, y, metric):
        return self.ad_dagger(y, x, metric) - self.ad(x, y)
