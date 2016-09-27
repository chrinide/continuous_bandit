from bayes_optim import BayesianOptimization
from sklearn.gaussian_process.kernels import Matern

# define using kernel
kernel = Matern(nu=.5)
# set parameter bounds. {"parameter name" : (minium, maxium), ...}
params = {"x" : (-10, 10)}
optim = BayesianOptimization(lambda x:(x - 1.) ** 2, params, kernel)
ret = kernel.maximize()
print ret["max"]

