"""Live correction and active sensing.

The model's ward probabilities are the prior. We treat their logits as a Gaussian field
whose correlation decays with distance between wards (nearby wards flood together because
they share rainfall cells, drains and low ground). A citizen report from ward j is a noisy
observation of that field; a Gaussian update then shifts ward j *and its neighbours*.

Active sensing picks the ward whose report would most reduce uncertainty where it matters:
uncertain wards (p near 0.5) with many people.
"""
import numpy as np

FLOODED_LOGIT = 3.0   # a "flooded" report pulls the logit toward p≈0.95
DRY_LOGIT = -3.0      # a "dry here" report pulls toward p≈0.05
OBS_VAR = 0.5         # citizen reports are noisy


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-z))


def kernel(lat, lon, length_km=2.5, prior_var=2.0):
    """Squared-exponential covariance between ward centroids."""
    y = np.asarray(lat) * 111.0
    x = np.asarray(lon) * 108.0
    d2 = (x[:, None] - x[None]) ** 2 + (y[:, None] - y[None]) ** 2
    return prior_var * np.exp(-d2 / (2 * length_km ** 2))


class LiveField:
    def __init__(self, p_prior, K):
        self.mu = logit(np.asarray(p_prior, dtype=float))
        self.S = K.copy()
        self.observed = []

    @property
    def p(self):
        return sigmoid(self.mu)

    @property
    def var(self):
        return np.diag(self.S).copy()

    def observe(self, j, flooded: bool, obs_var=OBS_VAR):
        # One-sided: "flooded" never lowers a ward's chance and "dry" never raises it
        # (a dry report on a ward already below ~5% would otherwise nudge it up).
        z = max(FLOODED_LOGIT, self.mu[j]) if flooded else min(DRY_LOGIT, self.mu[j])
        s = self.S[:, j]
        gain = s / (self.S[j, j] + obs_var)
        self.mu = self.mu + gain * (z - self.mu[j])
        self.S = self.S - np.outer(gain, s)
        self.observed.append((int(j), bool(flooded)))

    def query_scores(self, pop, obs_var=OBS_VAR):
        """Expected value of asking ward j: population-weighted variance reduction at
        wards whose decision is uncertain (p(1-p) is largest at p=0.5)."""
        p = self.p
        weight = np.asarray(pop, float) * p * (1 - p)
        reduction = self.S ** 2 / (np.diag(self.S)[None, :] + obs_var)  # [i, j]
        score = weight @ reduction
        for j, _ in self.observed:
            score[j] = -np.inf
        return score

    def next_query(self, pop):
        return int(np.argmax(self.query_scores(pop)))
