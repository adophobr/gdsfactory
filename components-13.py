import gdsfactory as gf

c = gf.components.bend_circular(angle=90, npoints=720, with_cladding_box=True)
c.plot()