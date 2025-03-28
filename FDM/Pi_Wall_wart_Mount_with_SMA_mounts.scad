difference(){
union() {
//translate([0,0,0])cube([65,58,35], center=true);
translate([0,0,2]) rotate([0,0,0])   cylinder(h=30, r1=42, r2=42, center=true,$fn=128);
translate([30,0,2])cube([7,65,30], center=true);

}

difference() {
translate([-2,0,2]) rotate([0,0,0])   cylinder(h=30, r1=47.5, r2=47.5, center=true,$fn=128);
translate([-5,0,2]) rotate([0,0,0])   cylinder(h=30, r1=8, r2=49, center=true,$fn=128);
translate([-5,0,2]) rotate([0,0,0])   cylinder(h=30, r1=49, r2=8, center=true,$fn=128);
}

    //Space for wall wart
    translate([-9,0,4])cube([61,45,27], center=true);
    
    //Pi Zero holes  
    #translate([29,11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([29,-11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,-11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    
    //Pi 3B/4/5 holes  
    translate([29,24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([29,-24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,-24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    
    // Power Supply air flow
    translate([-1,0,0]) rotate([0,0,0])   cylinder(h=68, r1=22, r2=22, center=true,$fn=128);
    //translate([0,0,3]) rotate([0,90,0])   cylinder(h=80, r1=13, r2=13, center=true,$fn=128);
    

    //Slots for velcro ties
    translate([0,-24,20]) rotate([0,45,-90]) cube([30,15,2.5], center=true);
    translate([0,24,20]) rotate([0,45,90]) cube([30,15,2.5], center=true);
    
    //Reduce size
    translate([0,46,0])cube([70,27,60], center=true);
    translate([0,-46,0])cube([70,27,60], center=true);
    translate([45,0,0])cube([25,90,60], center=true);
    translate([-48,0,0])cube([25,70,60], center=true);
    translate([-38,0,20])cube([25,70,40], center=true);
    
    //Space for cable
    translate([-6,-39,1]) rotate([0,90,0])   cylinder(h=64, r1=13, r2=13,center=true,$fn=128);
    translate([-6,39,1]) rotate([0,90,0])   cylinder(h=64, r1=13, r2=13, center=true,$fn=128);
    translate([-35,0,4.5]) rotate([90,0,0])   cylinder(h=70, r1=13, r2=13, center=true,$fn=128);

}

translate([22,0,3])cube([1,47,25], center=true);
translate([2,23,3])cube([40,1,25], center=true);
translate([2,-23,3])cube([40,1,25], center=true);

// Remove the following if not mounting SMA

difference(){
union(){
//Fill gaps
translate([31,-32,-5]) rotate([0,90,0])   cylinder(h=3, r1=14, r2=14,center=true,$fn=128);
translate([31,32,-5]) rotate([0,90,0])   cylinder(h=3, r1=14, r2=14,center=true,$fn=128);
    
translate([31,-27,-12]) rotate([0,0,0])   cylinder(h=3.5, r1=17, r2=17,center=true,$fn=128);
translate([31,27,-12]) rotate([0,0,0])   cylinder(h=3.5, r1=17, r2=17,center=true,$fn=128);
}

//SMA Connectors
translate([-6,-34,-3]) rotate([0,90,0])   cylinder(h=80, r1=3.5, r2=3.5,center=true,$fn=128);
translate([-6,34,-3]) rotate([0,90,0])   cylinder(h=80, r1=3.5, r2=3.5, center=true,$fn=128);

//Bottom
translate([0,0,-28])cube([100,100,30], center=true);

//edges
translate([0,-43,0])rotate([72,0,0]) cube([100,100,8], center=true);
translate([0,43,0])rotate([-72,0,0]) cube([100,100,8], center=true);

translate([45,0,0])cube([25,90,60], center=true);

    //Pi Zero holes  
    #translate([29,11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([29,-11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,-11.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    
    //Pi 3B/4/5 holes  
    translate([29,24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([29,-24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);
    translate([-29,-24.5,-12])rotate([0,0,0])   cylinder(h=5.2, r1=1.7, r2=1.7, center=true,$fn=24);

}