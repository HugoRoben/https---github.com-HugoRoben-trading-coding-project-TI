"""Price option contracts and evaluate the synthetic long-call strategy.

black_scholes implements a scalar European option value per underlying share. strategies
applies a scenario-based entry rule and computes cash flows for one contract. simulation
orders fixture snapshots by availability and records each signal, fill, cancellation and
realized result. These calculations can run entirely in memory.
"""
