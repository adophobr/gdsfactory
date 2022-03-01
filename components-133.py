import gdsfactory as gf

c = gf.components.ring_single_dut(wg_width=0.5, gap=0.2, length_x=4, radius=5, length_y=0, with_component=True)
c.plot()