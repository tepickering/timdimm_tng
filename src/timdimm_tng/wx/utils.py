import math


__all__ = ["dewpoint"]


def dewpoint(temp, humidity):
    """
    Calculate the dewpoint temperature given the temperature
    in Celsius and relative humidity.
    """
    # Magnus formula with updated coeffcients from Alduchov and Eskridge (1996)
    magnus_A = 17.625
    magnus_B = 243.04
    gamma = ((magnus_A * temp) / (magnus_B + temp)) + math.log(humidity / 100.0)
    return (magnus_B * gamma) / (magnus_A - gamma)
