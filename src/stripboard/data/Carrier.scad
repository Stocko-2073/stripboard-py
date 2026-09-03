include <BOSL/transforms.scad>
include <BOSL/shapes.scad>

nozzle = is_undef(nozzle) ? 0.7 : nozzle;
columns = is_undef(columns) ? 34 : columns;
rows = is_undef(rows) ? 26 : rows;
boardThickness = is_undef(boardThickness) ? 1.6 : boardThickness;

pinDepth = 0.9;

w = columns * 2.54 + 4.5;
h = rows * 2.54 + 3;
d = nozzle * 6 + boardThickness + pinDepth;
difference() {
    cuboid([w+(4*nozzle),d,h+(4*nozzle)],align=V_FWD);
    up(10) fwd(2*nozzle) cuboid([w,pinDepth,h+20],align=V_FWD);
    up(10) fwd(4*nozzle + pinDepth) cuboid([w,boardThickness,h+20],align=V_FWD);
    up(10) fwd(2*nozzle) cuboid([w-4,10,h-4+20],align=V_FWD);
}
