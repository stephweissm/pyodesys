# -*- coding: utf-8 -*-
"""
Core functionality from OdeSys.

Note that it is possible to use new custom ODE integrators with pyodesys by
providing a module with two functions named ``integrate_adaptive`` and
``integrate_predefined``. See the ``pyodesys.integrators`` module for examples.
"""

from __future__ import absolute_import, division, print_function

import numpy as np

import os

from .util import ensure_3args
from .plotting import plot_result, plot_phase_plane


class OdeSys(object):
    """ Object representing an ODE system.

    ``OdeSys`` provides unified interface to:

    - scipy.integarte.ode
    - pygslodeiv2
    - pyodeint
    - pycvodes

    The numerical integration can be performed either in an :meth:`adaptive`
    or :meth:`predefined` mode. Where locations to report the solution is
    chosen by the stepper or the user respectively. For convenience in user
    code one may use :meth:`integrate` which automatically chooses between
    the two based on the length of ``xout`` provided by the user.

    Parameters
    ----------
    f: callback
        first derivatives of dependent variables (y) with respect to
        dependent variable (x). Signature rhs(x, y[:]) --> f[:] or
        rhs(x, y[:], p[:]) --> f[:] or
    jac: callback
        Jacobian matrix (dfdy). Required for implicit methods.
    dfdx: callback
        Signature dfdx(x, y[:], p[:]) -> out[:] (used by e.g. GSL)
    band: tuple of 2 integers or None (default: None)
        If jacobian is banded: number of sub- and super-diagonals
    names: iterable of strings (default: None)
        names of variables, e.g. used for plotting
    pre_processors: iterable of callables (optional)
        signature: f(x1[:], y1[:], params1[:]) -> x2[:], y2[:], params2[:].
        When modifying: insert at beginning.
    post_processors: iterable of callables (optional)
        signature: f(x2[:], y2[:, :], params2[:]) -> x1[:], y1[:, :],
        params1[:]
        When modifying: insert at end.

    Attributes
    ----------
    f_cb : callback
        for evaluating the vector of derivatives
    j_cb : callback
        for evaluating the Jacobian matrix of f
    names : iterable of strings
    internal_xout : 1D array of floats
        internal values of dependent variable before post-processing
    internal_yout : 2D (or higher) array of floats
        internal values of dependent variable before post-processing
    internal_params : 1D array of floats
        internal parameter values before post-processing

    Examples
    --------
    >>> odesys = OdeSys(lambda x, y, p: p[0]*x + p[1]*y[0]*y[0])
    >>> yout, info = odesys.predefined([1], [0, .2, .5], [2, 1])
    >>> print(info['success'])
    True


    Notes
    -----
    banded jacobians are supported by "scipy" and "cvode" integrators

    """

    def __init__(self, f, jac=None, dfdx=None, roots=None, nroots=None,
                 band=None, names=None, pre_processors=None,
                 post_processors=None):
        self.f_cb = ensure_3args(f)
        self.j_cb = ensure_3args(jac) if jac is not None else None
        self.dfdx_cb = dfdx
        self.roots_cb = roots
        self.nroots = nroots
        if band is not None:
            if not band[0] >= 0 or not band[1] >= 0:
                raise ValueError("bands needs to be > 0 if provided")
        self.band = band
        self.names = names
        self.pre_processors = pre_processors or []
        self.post_processors = post_processors or []

    def pre_process(self, xout, y0, params=()):
        """ Transforms input to internal values, used inernally. """
        try:
            nx = len(xout)
            if nx == 1:
                xout = (0*xout[0], xout[0])
        except TypeError:
            xout = (0*xout, xout)

        for pre_processor in self.pre_processors:
            xout, y0, params = pre_processor(xout, y0, params)
        return np.atleast_1d(xout), np.atleast_1d(y0), np.atleast_1d(params)

    def post_process(self, xout, yout, params):
        """ Transforms internal values to output, used inernally. """
        for post_processor in self.post_processors:
            xout, yout, params = post_processor(xout, yout, params)
        return xout, yout, params

    def adaptive(self, y0, x0, xend, params=(), **kwargs):
        """ Integrate with integrator chosen output.

        Parameters
        ----------
        integrator: str
            see :meth:`integrate`
        y0: array_like
            see :meth:`integrate`
        x0: float
            initial value of the independent variable
        xend: float
            final value of the independent variable
        params: array_like
            see :meth:`integrate`
        \*\*kwargs:
            see :meth:`integrate`

        Returns
        -------
        Same as :meth:`integrate`
        """
        return self.integrate((x0, xend), y0,
                              params=params, **kwargs)

    def predefined(self, y0, xout, params=(), **kwargs):
        """ Integrate with user chosen output.

        Parameters
        ----------
        integrator: str
            see :meth:`integrate`
        y0: array_like
            see :meth:`integrate`
        xout: array_like
        params: array_like
            see :meth:`integrate`
        \*\*kwargs:
            see :meth:`integrate`

        Returns
        -------
        Length 2 tuple: (yout, info)
            see :meth:`integrate`
        """
        xout, yout, info = self.integrate(xout, y0, params=params,
                                          force_predefined=True, **kwargs)
        return yout, info

    def integrate(self, xout, y0, params=(), **kwargs):
        """
        Integrate the system of ODE's.

        Parameters
        ----------
        xout: array_like or pair (start and final time) or float
            if float:
                make it a pair: (0, xout)
            if pair or length-2 array:
                initial and final value of the independent variable
            if array_like:
                values of independent variable report at
        y0: array_like
            Initial values at xout[0] for the dependent variables.
        params: array_like (default: tuple())
            Value of parameters passed to user-supplied callbacks.
        integrator: str or None
            Name of integrator, one of:
                - 'scipy': :meth:`_integrate_scipy`
                - 'gsl': :meth:`_integrate_gsl`
                - 'odeint': :meth:`_integrate_odeint`
                - 'cvode':  :meth:`_integrate_cvode`

            See respective method for more information.
            If ``None``: ``os.environ.get('PYODESYS_INTEGRATOR', 'scipy')``
        atol: float
            Absolute tolerance
        rtol: float
            Relative tolerance
        with_jacobian: bool or None (default)
            Whether to use the jacobian. When ``None`` the choice is
            done automatically (only used when required). This matters
            when jacobian is derived at runtime (high computational cost).
        force_predefined: bool (default: False)
            override behaviour of ``len(xout) == 2`` => :meth:`adaptive`
        \*\*kwargs:
            Additional keyword arguments for ``_integrate_$(integrator)``.

        Returns
        -------
        Length 3 tuple: (xout, yout, info)
        xout: array of values of the independent variable
        yout: array of the dependent variable(s) for the different values of x
        info: dict ('nfev' is guaranteed to be a key)
        """
        intern_xout, intern_y0, self.internal_params = self.pre_process(
            xout, y0, params)
        integrator = kwargs.pop('integrator', None)
        if integrator is None:
            integrator = os.environ.get('PYODESYS_INTEGRATOR', 'scipy')
        if isinstance(integrator, str):
            nfo = getattr(self, '_integrate_' + integrator)(
                intern_xout, intern_y0, **kwargs)
        else:
            kwargs['with_jacobian'] = getattr(integrator,
                                              'with_jacobian', None)
            nfo = self._integrate(integrator.integrate_adaptive,
                                  integrator.integrate_predefined,
                                  intern_xout, intern_y0, **kwargs)

        self.internal_xout = np.asarray(
            nfo['internal_xout'], dtype=np.float64).copy()
        self.internal_yout = np.asarray(
            nfo['internal_yout'], dtype=np.float64).copy()
        return self.post_process(nfo['internal_xout'], nfo['internal_yout'],
                                 self.internal_params)[:2] + (nfo,)

    def _integrate_scipy(self, intern_xout, intern_y0, atol=1e-8, rtol=1e-8,
                         first_step=None, with_jacobian=None,
                         force_predefined=False, name=None, **kwargs):
        """ Do not use directly (use ``integrate('scipy', ...)``).

        Uses `scipy.integrate.ode <http://docs.scipy.org/doc/scipy/reference/\
generated/scipy.integrate.ode.html>`_

        Parameters
        ----------
        \*args:
            see :meth:`integrate`
        name: str (default: 'lsoda'/'dopri5' when jacobian is available/not)
            what integrator wrapped in scipy.integrate.ode to use.
        \*\*kwargs:
            keyword arguments passed onto `set_integrator(...) <\
http://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.ode.\
set_integrator.html#scipy.integrate.ode.set_integrator>`_

        Returns
        -------
        See :meth:`integrate`
        """
        ny = len(intern_y0)
        nx = len(intern_xout)
        if name is None:
            if self.j_cb is None:
                name = 'dopri5'
            else:
                name = 'lsoda'
        if with_jacobian is None:
            if name == 'lsoda':  # lsoda might call jacobian
                with_jacobian = True
            elif name in ('dop853', 'dopri5'):
                with_jacobian = False  # explicit steppers
            elif name == 'vode':
                with_jacobian = kwargs.get('method', 'adams') == 'bdf'
        from scipy.integrate import ode

        def rhs(t, y, p=()):
            rhs.ncall += 1
            return self.f_cb(t, y, p)
        rhs.ncall = 0

        if self.j_cb is not None:
            def jac(t, y, p=()):
                jac.ncall += 1
                return self.j_cb(t, y, p)
            jac.ncall = 0

        r = ode(rhs, jac=jac if with_jacobian else None)
        if 'lband' in kwargs or 'uband' in kwargs or 'band' in kwargs:
            raise ValueError("lband and uband set locally (set `band` at"
                             " initialization instead)")
        if self.band is not None:
            kwargs['lband'], kwargs['uband'] = self.band
        r.set_integrator(name, atol=atol, rtol=rtol, **kwargs)
        if len(self.internal_params) > 0:
            r.set_f_params(self.internal_params)
            r.set_jac_params(self.internal_params)
        r.set_initial_value(intern_y0, intern_xout[0])
        if nx == 2 and not force_predefined:
            # vode itask 2 (may overshoot)
            ysteps = [intern_y0]
            xsteps = [intern_xout[0]]
            while r.t < intern_xout[1]:
                r.integrate(intern_xout[1], step=True)
                if not r.successful():
                    raise RuntimeError("failed")
                xsteps.append(r.t)
                ysteps.append(r.y)
            yout = np.array(ysteps)
            intern_xout = np.array(xsteps)
        else:
            yout = np.empty((nx, ny))
            yout[0, :] = intern_y0
            for idx in range(1, nx):
                r.integrate(intern_xout[idx])
                if not r.successful():
                    raise RuntimeError("failed")
                yout[idx, :] = r.y
        info = {
            'internal_xout': intern_xout,
            'internal_yout': yout,
            'success': r.successful(),
            'nfev': rhs.ncall,
        }
        if self.j_cb is not None:
            info['njev'] = jac.ncall
        return info

    def _integrate(self, adaptive, predefined, intern_xout, intern_y0,
                   atol=1e-8, rtol=1e-8, first_step=None, with_jacobian=None,
                   force_predefined=False, **kwargs):
        if first_step is None:
            first_step = 1e-14 + abs(intern_xout[0])*1e-14  # arbitrary, heur.
        nx = len(intern_xout)
        new_kwargs = dict(dx0=first_step, atol=atol,
                          rtol=rtol, check_indexing=False)
        new_kwargs.update(kwargs)

        def _f(x, y, fout):
            if len(self.internal_params) > 0:
                fout[:] = self.f_cb(x, y, self.internal_params)
            else:
                fout[:] = self.f_cb(x, y)

        if with_jacobian is None:
            raise ValueError("Need to pass with_jacobian")
        elif with_jacobian is True:
            def _j(x, y, jout, dfdx_out=None, fy=None):
                if len(self.internal_params) > 0:
                    jout[:, :] = self.j_cb(x, y, self.internal_params)
                else:
                    jout[:, :] = self.j_cb(x, y)
                if dfdx_out is not None:
                    if len(self.internal_params) > 0:
                        dfdx_out[:] = self.dfdx_cb(x, y, self.internal_params)
                    else:
                        dfdx_out[:] = self.dfdx_cb(x, y)
        else:
            _j = None

        if self.roots_cb is not None:
            def _roots(x, y, out):
                if len(self.internal_params) > 0:
                    out[:] = self.roots_cb(x, y, self.internal_params)
                else:
                    out[:] = self.roots_cb(x, y)
            if 'roots' in new_kwargs:
                raise ValueError("cannot override roots")
            else:
                new_kwargs['roots'] = _roots
                if 'nroots' in new_kwargs:
                    raise ValueError("cannot override nroots")
                new_kwargs['nroots'] = self.nroots
        if nx == 2 and not force_predefined:
            intern_xout, yout, info = adaptive(_f, _j, intern_y0, *intern_xout,
                                               **new_kwargs)
        else:
            yout, info = predefined(_f, _j, intern_y0, intern_xout,
                                    **new_kwargs)
        info['internal_xout'] = intern_xout
        info['internal_yout'] = yout
        return info

    def _integrate_gsl(self, *args, **kwargs):
        """ Do not use directly (use ``integrate('gsl', ...)``).

        Uses `GNU Scientific Library <http://www.gnu.org/software/gsl/>`_
        (via `pygslodeiv2 <https://pypi.python.org/pypi/pygslodeiv2>`_)
        to integrate the ODE system.

        Parameters
        ----------
        \*args:
            see :meth:`integrate`
        method: str (default: 'bsimp')
            what stepper to use, see :py:attr:`gslodeiv2.steppers`
        \*\*kwargs:
            keyword arguments passed onto
            :py:func:`gslodeiv2.integrate_adaptive`/:py:func:`gslodeiv2.integrate_predefined`

        Returns
        -------
        See :meth:`integrate`
        """
        import pygslodeiv2  # Python interface GSL's "odeiv2" integrators
        kwargs['with_jacobian'] = kwargs.get(
            'method', 'bsimp') in pygslodeiv2.requires_jac
        return self._integrate(pygslodeiv2.integrate_adaptive,
                               pygslodeiv2.integrate_predefined,
                               *args, **kwargs)

    def _integrate_odeint(self, *args, **kwargs):
        """ Do not use directly (use ``integrate('odeint', ...)``).

        Uses `Boost.Numeric.Odeint <http://www.odeint.com>`_
        (via `pyodeint <https://pypi.python.org/pypi/pyodeint>`_) to integrate
        the ODE system.
        """
        import pyodeint  # Python interface to boost's odeint integrators
        kwargs['with_jacobian'] = kwargs.get(
            'method', 'rosenbrock4') in pyodeint.requires_jac
        return self._integrate(pyodeint.integrate_adaptive,
                               pyodeint.integrate_predefined,
                               *args, **kwargs)

    def _integrate_cvode(self, *args, **kwargs):
        """ Do not use directly (use ``integrate('cvode', ...)``).

        Uses CVode from CVodes in
        `SUNDIALS <https://computation.llnl.gov/casc/sundials/>`_
        (via `pycvodes <https://pypi.python.org/pypi/pycvodes>`_)
        to integrate the ODE system. """
        import pycvodes  # Python interface to SUNDIALS's cvodes integrators
        kwargs['with_jacobian'] = kwargs.get(
            'method', 'bdf') in pycvodes.requires_jac
        if 'lband' in kwargs or 'uband' in kwargs or 'band' in kwargs:
            raise ValueError("lband and uband set locally (set at"
                             " initialization instead)")
        if self.band is not None:
            kwargs['lband'], kwargs['uband'] = self.band
        return self._integrate(pycvodes.integrate_adaptive,
                               pycvodes.integrate_predefined,
                               *args, **kwargs)

    def _plot(self, cb, internal_xout=None, internal_yout=None,
              internal_params=None, **kwargs):
        kwargs = kwargs.copy()
        if 'x' in kwargs or 'y' in kwargs or 'params' in kwargs:
            raise ValueError("x and y from internal_xout and internal_yout")

        if 'post_processors' not in kwargs:
            kwargs['post_processors'] = self.post_processors

        if 'names' not in kwargs:
            kwargs['names'] = getattr(self, 'names', None)
        if (internal_xout, internal_yout, internal_params) == (None,)*3:
            internal_xout = self.internal_xout
            internal_yout = self.internal_yout
            internal_params = self.internal_params
        elif None in (internal_xout, internal_yout, internal_params):
            raise ValueError("Pass either all or none of internal_* kwargs")
        return cb(internal_xout, internal_yout, internal_params, **kwargs)

    def plot_result(self, **kwargs):
        """ Plots the integrated dependent variables from last integration.

        See :func:`pyodesys.plotting.plot_result`
        """
        return self._plot(plot_result, **kwargs)

    def plot_phase_plane(self, indices=None, **kwargs):
        """ Plots a phase portrait from last integration.

        See :func:`pyodesys.plotting.plot_phase_plane`
        """
        return self._plot(plot_phase_plane, indices=indices, **kwargs)

    def _jac_eigenvals_svd(self, xval, yvals, intern_p):
        from scipy.linalg import svd
        J = self.j_cb(xval, yvals, intern_p)
        return svd(J, compute_uv=False)

    def stiffness(self, xyp=None, eigenvals_cb=None):
        """ Running stiffness ratio from last integration.

        Calculate sittness ratio, i.e. the ratio between the largest and
        smallest absolute eigenvalue of the jacobian matrix (from SVD).
        Note that this is a very expensive method for any but the smallest
        systems.

        Parameters
        ----------
        xyp: length 3 tuple (default: None)
            internal_xout, internal_yout, internal_params, taken
            from last integration if not specified.
        eigenvals_cb: callback (optional)
            signature (x, y, p) (internal variables)

        """
        if eigenvals_cb is None:
            if self.band is not None:
                raise NotImplementedError
            eigenvals_cb = self._jac_eigenvals_svd

        if xyp is None:
            x, y, intern_p = (self.internal_xout, self.internal_yout,
                              self.internal_params)
        else:
            x, y, intern_p = self.pre_process(*xyp)

        singular_values = []
        for xval, yvals in zip(x, y):
            singular_values.append(eigenvals_cb(xval, yvals, intern_p))

        return (np.abs(singular_values).max(axis=-1) /
                np.abs(singular_values).min(axis=-1))
