import gdsfactory as gf

c = gf.components.mzit(w0=0.5, w1=0.45, w2=0.55, dy=2.0, delta_length=10.0, Ls=1.0, coupler_length1=5.0, coupler_length2=10.0, coupler_gap1=0.2, coupler_gap2=0.3, bend_radius=10.0, taper_length=5.0)
c.plot()