"""Light unit conversions shared by the simulator and the controller."""

PAR_UMOL_PER_W_GLOBAL = 2.06  # umol/m2/s PAR per W/m2 of global solar radiation (~45 % PAR)
LUX_PER_W_GLOBAL = 110.0  # luminous efficacy of daylight
LUX_PER_UMOL_SUN = LUX_PER_W_GLOBAL / PAR_UMOL_PER_W_GLOBAL  # ~53 lux per umol/m2/s
LUX_PER_UMOL_LED = 70.0  # typical full-spectrum white LED
J_PER_UMOL_PAR = 0.218  # radiant energy of 1 umol PAR photons
