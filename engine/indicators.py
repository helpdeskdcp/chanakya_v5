def simple_moving_average(data, period):
    return sum(data[-period:]) / period

def exponential_moving_average(data, period):
    sum_weights = sum(range(1, period+1))
    weighted_sum = sum(i * x for i, x in enumerate(data[-period:], 1))
    return weighted_sum / sum_weights

def relative_strength_index(closes, period=14):
    delta = [x - y for y, x in zip(closes, closes[1:])]
    up, down = [x for x in delta if x > 0], [x for x in delta if x < 0]
    up_avg = sum(up[-period:]) / period if period <= len(up) else 0
    down_avg = sum(abs(x) for x in down[-period:]) / period if period <= len(down) else 0
    rs = up_avg / down_avg if down_avg!= 0 else 0
    return 100 - (100 / (1 + rs))

def moving_average_convergence_divergence(closes, short_window, long_window):
    short_ema = exponential_moving_average(closes, short_window)
    long_ema = exponential_moving_average(closes, long_window)
    return short_ema - long_ema

def bollinger_bands(data, period, num_std):
    mean = sum(data[-period:]) / period
    variance = sum((x - mean) ** 2 for x in data[-period:]) / period
    std_dev = variance ** 0.5
    upper_band = mean + num_std * std_dev
    lower_band = mean - num_std * std_dev
    return upper_band, lower_band
