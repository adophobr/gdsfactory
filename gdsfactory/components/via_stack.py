from typing import Optional, Tuple

from numpy import floor

import gdsfactory as gf
from gdsfactory.component import Component
from gdsfactory.components.compass import compass
from gdsfactory.components.via import via1, via2, via3
from gdsfactory.tech import LAYER
from gdsfactory.types import ComponentOrFactory, Layer


@gf.cell
def via_stack(
    size: Tuple[float, float] = (11.0, 11.0),
    layers: Tuple[Layer, ...] = (LAYER.M1, LAYER.M2, LAYER.M3),
    vias: Optional[Tuple[Optional[ComponentOrFactory], ...]] = (via2, via3),
    layer: Optional[Layer] = None,
) -> Component:
    """Rectangular via_stack

    Args:
        size: (tuple) Width and height of rectangle.
        layers: layers on which to draw rectangles
        vias: vias to use to fill the rectangles
        layer: port layer
    """

    width, height = size
    a = width / 2
    b = height / 2
    layer_port = layer or layers[-1]

    c = Component()
    c.height = height

    for layer in layers:
        ref = c << compass(size=(width, height), layer=layer)

        if layer == layer_port:
            c.add_ports(ref.ports)

    vias = vias or []
    for via in vias:
        if via is not None:
            via = via() if callable(via) else via

            w = via.info["width"]
            h = via.info["height"]
            g = via.info["enclosure"]
            pitch_x = via.info["pitch_x"]
            pitch_y = via.info["pitch_y"]

            nb_vias_x = (width - w - 2 * g) / pitch_x + 1
            nb_vias_y = (height - h - 2 * g) / pitch_y + 1

            nb_vias_x = int(floor(nb_vias_x)) or 1
            nb_vias_y = int(floor(nb_vias_y)) or 1
            ref = c.add_array(
                via, columns=nb_vias_x, rows=nb_vias_y, spacing=(pitch_x, pitch_y)
            )

            cw = (width - (nb_vias_x - 1) * pitch_x - w) / 2
            ch = (height - (nb_vias_y - 1) * pitch_y - h) / 2
            x0 = -a + cw + w / 2
            y0 = -b + ch + h / 2
            ref.move((x0, y0))

    return c


via_stack_metal = gf.partial(
    via_stack,
    layers=(LAYER.M1, LAYER.M2, LAYER.M3),
    vias=(via2, via3),
)

via_stack_slab = gf.partial(
    via_stack,
    layers=(LAYER.SLAB90, LAYER.M1, LAYER.M2, LAYER.M3),
    vias=(via1, via2, via3),
)
via_stack_slab_npp = gf.partial(
    via_stack,
    layers=(LAYER.SLAB90, LAYER.Npp, LAYER.M1, LAYER.M2, LAYER.M3),
    vias=(via1, via2, via3),
)
via_stack_heater = gf.partial(
    via_stack, layers=(LAYER.HEATER, LAYER.M2, LAYER.M3), vias=(via2, via3)
)


if __name__ == "__main__":
    c = via_stack()
    c.show()
