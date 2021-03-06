from __future__ import print_function
from __future__ import division
import numpy as np
from scipy.optimize import differential_evolution
from helpers import PrintLog
from scipy.linalg import cholesky, cho_solve
    
class _PyGaussianProcess:
    def __init__(self, kernel, alpha=1e-3):
        self.kernel_ = kernel
        self.alpha = alpha
        
    def fit(self, sample_X, sample_y):
        self.y_mean = np.mean(sample_y, axis=0)
        sample_y = sample_y - self.y_mean
        self.X_mean = np.mean(sample_X, axis=0)
        self.X_std = np.std(sample_X, axis=0)
        sample_X = (sample_X - self.X_mean) / self.X_std
        
        self.X_train_ = sample_X
        K = self.kernel_(self.X_train_)
        K[np.diag_indices_from(K)] += self.alpha
        self.L_ = cholesky(K, lower=True)  # Line 2
        self.alpha_ = cho_solve((self.L_, True), sample_y)  # Line 3

        #kernel_predict = KernelPredict()
    def predict(self, sample_X):
        sample_X = (sample_X - self.X_mean) / self.X_std
        K_trans = self.kernel_(sample_X, self.X_train_)
        y_mean = K_trans.dot(self.alpha_)  # Line 4 (y_mean = f_star)
        y_mean = self.y_mean + y_mean  # undo normal.
        v = cho_solve((self.L_, True), K_trans.T)  # Line 5
        y_cov = self.kernel_(sample_X) - K_trans.dot(v)  # Line 6
        return y_mean, y_cov
        
class _Ucb:
    def __init__(self, estimator, kappa):
        self.estimator = estimator
        self.kappa = kappa
        
    def getScore(self, x):
        mean, var = self.estimator.predict(x)
        return mean + self.kappa * np.sqrt(var)

class BayesianOptimization(object):
    """
        :param f: callable
            Function to be maximized.

        :param pbounds: dict
            Dictionary with parameters names as keys and a tuple with minimum
            and maximum values.
            e.g. {"parameter name1": (minium value, maxium value), "parameter name2": (minium value, maxium value), ...}
        :param kernel: mixed
            Kernel Object of gaussian_process of scikit-learn
        :param verbose: int
            Whether or not to print progress.

    """
    def __init__(self, f, pbounds, kernel, kappa=2.576, verbose=1, gp_regulation=1e-2):
        
        # Store the original dictionary
        self.pbounds = pbounds

        # Get the name of the parameters
        self.keys = list(pbounds.keys())

        # Find number of parameters
        self.dim = len(pbounds)

        # Create an array with parameters bounds
        self.bounds = []
        for key in self.pbounds.keys():
            self.bounds.append(self.pbounds[key])
        self.bounds = np.asarray(self.bounds)

        # Some function to be optimized
        self.f = f

        # Initialization flag
        self.initialized = False

        # Initialization lists --- stores starting points before process begins
        self.init_points = []
        self.x_init = []
        self.y_init = []

        # Numpy array place holders
        self.X = None
        self.Y = None

        # Counter of iterations
        self.i = 0

        # Since scipy 0.16 passing lower and upper bound to theta seems to be
        # broken. However, there is a lot of development going on around GP
        # is scikit-learn. So I'll pick the easy route here and simple specify
        # only theta0.
        
        self.gp = _PyGaussianProcess(kernel=kernel, alpha=gp_regulation)
        
        # PrintLog object
        self.plog = PrintLog(self.keys)

        # Output dictionary
        self.res = {}
        # Output dictionary
        self.res['max'] = {'max_val': None,
                           'max_params': None}
        self.res['all'] = {'values': [], 'params': []}

        # Verbose
        self.verbose = verbose
        
        self.ucb = _Ucb(self.gp, kappa)

    def _acq_max(self):
        x_max = self.bounds[:, 0]
        max_acq = None

        x_tries = np.random.uniform(self.bounds[:, 0], self.bounds[:, 1],
                                    size=(1, self.bounds.shape[0]))

        for x_try in x_tries:
            # Find the minimum of minus the acquisition function
            res = differential_evolution(lambda x: -self.ucb.getScore(x.reshape(1, -1)), self.bounds, tol=0.001, maxiter=400, popsize=100)
            # Store it if better than previous minimum(maximum).
            if max_acq is None or -res.fun >= max_acq:
                x_max = res.x
                max_acq = -res.fun

        # Clip output to make sure it lies within the bounds. Due to floating
        # point technicalities this is not always the case.
        return np.clip(x_max, self.bounds[:, 0], self.bounds[:, 1])
    
    def init(self, init_points=5):
        """
        Initialization method to kick start the optimization process. It is a
        combination of points passed by the user, and randomly sampled ones.

        :param init_points:
            Number of random points to probe.
        """

        # Generate random points
        l = [np.random.uniform(x[0], x[1], size=init_points) for x in self.bounds]

        # Concatenate new random points to possible existing
        # points from self.explore method.
        self.init_points += list(map(list, zip(*l)))

        # Create empty list to store the new values of the function
        y_init = []

        # Evaluate target function at all initialization
        # points (random + explore)
        for x in self.init_points:

            y_init.append(self.f(**dict(zip(self.keys, x))))

            if self.verbose:
                self.plog.print_step(x, y_init[-1])

        # Append any other points passed by the self.initialize method (these
        # also have a corresponding target value passed by the user).
        self.init_points += self.x_init

        # Append the target value of self.initialize method.
        y_init += self.y_init

        # Turn it into np array and store.
        self.X = np.asarray(self.init_points)
        self.Y = np.asarray(y_init)

        # Updates the flag
        self.initialized = True

    def explore(self, points_dict):
        """
        Method to explore user defined points

        :param points_dict:
            explore points
            e.g. {"parameter name1": (explore value1, explore value2, ... ), "parameter name2": (explore value1, explore value2, ... ), ...}
        :return: Nothing
        """

        # Consistency check
        param_tup_lens = []

        for key in self.keys:
            param_tup_lens.append(len(list(points_dict[key])))

        if all([e == param_tup_lens[0] for e in param_tup_lens]):
            pass
        else:
            raise ValueError('The same number of initialization points '
                             'must be entered for every parameter.')

        # Turn into list of lists
        all_points = []
        for key in self.keys:
            all_points.append(points_dict[key])

        # Take transpose of list
        self.init_points = list(map(list, zip(*all_points)))

    def initialize(self, points_dict):
        """
        Method to introduce point for which the target function
        value is known

        :param points_dict:
        :return:
        """

        for target in points_dict:

            self.y_init.append(target)

            all_points = []
            for key in self.keys:
                all_points.append(points_dict[target][key])

            self.x_init.append(all_points)

    def set_bounds(self, new_bounds):
        """
        A method that allows changing the lower and upper searching bounds

        :param new_bounds:
            A dictionary with the parameter name and its new bounds

        """

        # Update the internal object stored dict
        self.pbounds.update(new_bounds)

        # Loop through the all bounds and reset the min-max bound matrix
        for row, key in enumerate(self.pbounds.keys()):

            # Reset all entries, even if the same.
            self.bounds[row] = self.pbounds[key]

    def userInit(self, init_points=5):
        self.init(init_points)

    def ones(self):
        self.gp.fit(self.X, self.Y)
        x_max = self._acq_max()
        
        if np.any((self.X - x_max).sum(axis=1) == 0):
            x_max = np.random.uniform(self.bounds[:, 0],
                                      self.bounds[:, 1],
                                      size=self.bounds.shape[0])
                                      
        self.X = np.vstack((self.X, x_max.reshape((1, -1))))
        self.Y = np.append(self.Y, self.f(**dict(zip(self.keys, x_max))))
            
        self.plog.print_summary()
        
        self.res['max'] = {'max_val': self.Y.max(),
                           'max_params': dict(zip(self.keys, self.X[self.Y.argmax()]))
                          }
        self.res['all']['values'].append(self.Y[-1])
        self.res['all']['params'].append(dict(zip(self.keys, self.X[-1])))
        
        return self.Y[-1]
        
    def maximize(self, init_points=5, n_iter=25, **gp_params):
        """
        Main optimization method.
        
        :param init_points: int
            number of initial exploer point that decisioned by random
        :param n_iter: int
            number of iteration of exploer
        :return: dict
            max parameter and all exploered parameter's point
        
        """
        # Reset timer
        self.plog.reset_timer()

        # Initialize x, y and find current y_max
        if not self.initialized:
            if self.verbose:
                self.plog.print_header()
            self.init(init_points)

        y_max = self.Y.max()

        # Set parameters if any was passed
        # self.gp.set_params(**gp_params)

        self.gp.fit(self.X, self.Y)

        # Finding argmax of the acquisition function.
        x_max = self._acq_max()

        # Print new header
        if self.verbose:
            self.plog.print_header(initialization=False)
       
        for i in range(n_iter):
            # Test if x_max is repeated, if it is, draw another one at random
            # If it is repeated, print a warning
            
            pwarning = False
            """
            if np.any((self.X - x_max).sum(axis=1) == 0):

                x_max = np.random.uniform(self.bounds[:, 0],
                                          self.bounds[:, 1],
                                          size=self.bounds.shape[0])

                pwarning = True
            """
            
            # Append most recently generated values to X and Y arrays
            self.X = np.vstack((self.X, x_max.reshape((1, -1))))
            self.Y = np.append(self.Y, self.f(**dict(zip(self.keys, x_max))))
            
            self.gp.fit(self.X, self.Y)

            # Update maximum value to search for next probe point.
            if self.Y[-1] > y_max:
                y_max = self.Y[-1]

            # Maximize acquisition function to find next probing point
            x_max = self._acq_max()

            # Print stuff
            if self.verbose:
                self.plog.print_step(self.X[-1], self.Y[-1], warning=pwarning)

            # Keep track of total number of iterations
            self.i += 1

            self.res['max'] = {'max_val': self.Y.max(),
                               'max_params': dict(zip(self.keys,
                                                      self.X[self.Y.argmax()]))
                               }
            self.res['all']['values'].append(self.Y[-1])
            self.res['all']['params'].append(dict(zip(self.keys, self.X[-1])))

        # Print a final report if verbose active.
        if self.verbose:
            self.plog.print_summary()
            
        return self.res
        
