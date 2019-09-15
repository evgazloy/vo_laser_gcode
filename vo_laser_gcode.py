'''
VO Laser G-Code Generator
Copyright (C) 2019 Evgeniy Metelev <evgazloy@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
'''

import sys
import os

sys.path.append('/usr/share/inkscape/extensions')
sys.path.append('/Applications/Inkscape.app/Contents/Resources/extensions')

import subprocess
import math
import re

import inkex
import png
import array

inkex.localize()

class GCodeHolder:
    def __init__(self, resolution, power):
        self.header = ""
        self.gcode = ""
        self.footer = ""
        self.homing = ""
        self.resolution = resolution
        self.val = 255
        self.os_started = False
        self.os_end = -1.
        self.power = power

    def setHoming(self, homing):
        self.homing = "$H" if homing == 1 else "G28" if self.homing == 2 else ""
        if self.homing:
            self.homing += "; Home all axes\n"

    def createDefaultHeader(self, e_speed, t_speed = None):
        if not t_speed:
            t_speed = e_speed

        self.header = "; Generated with:\n"
        self.header += "; VO Laser G-Code Generator\n"
        self.header += "; by Evgeniy Metelev\n;\n{}".format(self.homing)
        self.header += "G21; Set units to millimeters\n"
        self.header += "G90; Use absolute coordinates\n"
        self.header += "G92; Coordinate offset\n"
        self.header += "G00 {}; Set travel feed\n".format(t_speed)
        self.header += "G01 {}; Set engraving feed\n".format(e_speed)
        self.header += "M03 S0; Ready laser\n"
    
    def createDefaultFooter(self):
        self.footer = "M05; Laser off\n\
            G00 X0 Y0; Home\n{h}".format( h = self.homing )

    def addGCode(self, x, y, old, val):
        self.gcode += "G0{cmd} X{x} Y{y} S{s}\n".format(cmd=(0 if old == 255 else 1),\
            x=x, y=y, s=int((float(255 - val) / self.power) * 100.))

    def addPixel(self, x, y, val, border, overscan = 0., vertical = False):
        _x = float(x) / self.resolution
        _y = float(y) / self.resolution

        if (overscan != 0.) and border and self.os_started:
            self.os_started = False
            if (self.os_end < 0):
                self.os_end = _x if not vertical else _y

            if not vertical:
                self.addGCode(self.os_end + overscan, _y, 255, 255)
            else:
                self.addGCode(_x, self.os_end - overscan, 255, 255)

        if ( (val != self.val) or (border and (val != 255)) ):
            if overscan != 0.:
                if (val != 255) and (not self.os_started):
                    self.os_started = True
                    if not vertical:
                        self.addGCode(_x - overscan, _y, 255, 255)
                    else:
                        self.addGCode(_x, _y + overscan, 255, 255)
                
                if(val == 255) and self.os_started:
                    self.os_end = _x if not vertical else _y

            self.addGCode(_x, _y, self.val, val)
            self.val = val
        
    def compile(self):
        return self.header + self.gcode + self.footer

    def add(self, gcode):
        self.footer += gcode


class VOLaserGCode(inkex.Effect):
    def __init__(self):
        inkex.Effect.__init__(self)

        self.OptionParser.add_option("-d", "--directory", action = "store", type = "string",\
            dest = "directory", default = "", help = "Directory for files")
        self.OptionParser.add_option("-f", "--filename", action = "store", type = "string",\
             dest = "filename", default = "gcode.txt", help = "File name")
        self.OptionParser.add_option("-o", "--overwrite", action = "store", type = "inkbool",\
             dest = "overwrite", default = True, help = "Overwrite or add numeric suffix to filename")
        self.OptionParser.add_option("-b", "--bg_color", action = "store", type = "string",\
             dest = "bg_color", default = "#ffffff", help = "Replace transparency with selected color")
        self.OptionParser.add_option("-r", "--resolution", action = "store", type = "int",\
             dest = "resolution", default = "10", help = "Resolution of image in pixels/mm")
        self.OptionParser.add_option("-t", "--grayscale_type", action = "store", type = "int",\
             dest = "grayscale_type", default = "1", help = "Grayscale conversion algorithm")
        self.OptionParser.add_option("-s", "--speed", action = "store", type = "int",\
             dest = "speed", default = "800", help = "Engraving speed mm/min")
        self.OptionParser.add_option("-c", "--cross", action = "store", type = "inkbool",\
             dest = "cross", default = False, help = "Engrave cross-hatch pattern (horizontal then verical)")
        self.OptionParser.add_option("", "--homing", action = "store", type = "int", \
            dest = "homing", default = "1", help = "Homing command")
        self.OptionParser.add_option("", "--overscanning", action = "store", type = "int",\
             dest = "overscanning", default = "0", help = "Distance to overscan")
        self.OptionParser.add_option("-p", "--max_power", action = "store", type = "int",\
             dest = "max_power", default = "100", help = "Max power in percent")
        self.OptionParser.add_option("", "--pause", action = "store", type = "inkbool",\
             dest = "pause", default = False, help = "Pause program before vertical engraving")

    def check_dir(self):
        if (os.path.isdir(self.options.directory)):
            if "." in self.options.filename:
                r = re.match(r"^(.*)(\..*)$", self.options.filename)
                name = r.group(1)
                ext = r.group(2)
            else:
                name = self.options.filename
                ext = ""

            if not self.options.overwrite:
                dir_list = os.listdir(self.options.directory)

                max_n = 0
                for s in dir_list:
                    r = re.match(r"${n}_0*(\d+){e}$".format( n = re.escape(name), e = re.escape(ext)), s)
                    if r:
                        max_n = max(max_n, r.group(1))
                
                name = name + "_" + ( "0" * (2 - len(str(max_n)) + str(max_n + 1)))

            self.gcode_filename = os.path.join(self.options.directory, name + ext)
            self.png_filename = os.path.join(self.options.directory, name + ".png")
            self.preview_filename = os.path.join(self.options.directory, name + "_preview.png")
            
            try:
                filename = (self.gcode_filename, self.png_filename, self.preview_filename)
                for name in filename:
                    f = open(name, "w")
                    f.close()
            except:
                inkex.errormsg("{n}:\nWrite failed.".format( n = name))
                raise RuntimeError
        else:
            inkex.errormsg("Directory not exist")
            raise RuntimeError

    def png_export(self):
        current_file = self.args[-1]
        cmd = "inkscape -C -e \"{pr}\" -b\"{bg}\" {fn} -d {dpi}"\
            .format(pr = self.png_filename, bg = self.options.bg_color,\
                fn = current_file, dpi = 25.4 * self.options.resolution)

        p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return_code = p.wait()

        if return_code:
            inkex.errormsg("Inkscape error:\n{err}".format(err = p.stderr))
            raise RuntimeError

    def grayscale_convert(self, r, g, b):
        result = (r * 0.21 + g * 0.71 + b * 0.07) if self.options.grayscale_type == 1 else\
            ((r + g + b) / 3) if self.options.grayscale_type == 2 else\
                r if self.options.grayscale_type == 3 else\
                    g if self.options.grayscale_type == 4 else\
                        b if self.options.grayscale_type == 5 else\
                            max(r, g, b) if self.options.grayscale_type == 6 else\
                                min(r, g, b)

        return int(result)

    def generate_gcode(self):
        reader = png.Reader(self.png_filename)
        w, h, pixels, metadata = reader.read_flat()

        h_gcode = GCodeHolder(self.options.resolution, self.options.max_power)
        h_gcode.setHoming(self.options.homing)
        h_gcode.createDefaultHeader(self.options.speed)
        
        if self.options.cross:
            v_gcode = GCodeHolder(self.options.resolution, self.options.max_power)
            v_gcode.createDefaultFooter()
        else:
            h_gcode.createDefaultFooter()
        
        gray = [[255 for i in range(w)] for j in range(h)]

        for i in range(w * h):
            h_x = i % w
            h_y = i // w
            size = 4 if metadata['alpha'] else 3
            pos = i * size
            overscan = self.options.overscanning

            if h_y % 2 == 1:
                d = w - 2 * h_x - 1
                h_x += d
                pos += d * size
                overscan *= -1

            def convert(p):
                r = pixels[p]
                g = pixels[p + 1]
                b = pixels[p + 2]
                return self.grayscale_convert(r, g, b)

            val = convert(pos)
            gray[h_y][h_x] = val

            h_y = h - h_y - 1
            border = (h_x == 0) or (h_x == w - 1)

            h_gcode.addPixel(h_x, h_y, val, border, overscan)

            if self.options.cross:
                overscan = self.options.overscanning
                v_x = i // h
                v_y = i % h
                if v_x % 2 == 0:
                    d = 0
                else:
                    d = h - 2 * v_y - 1
                    v_y += d
                    overscan *= -1

                pos = (v_y * w + v_x) * size
                v_y = h - v_y - 1
                border = (v_y == 0) or (v_y == h - 1)
                v_gcode.addPixel(v_x, v_y, convert(pos), border, overscan, True)
            
        preview_io = open(self.preview_filename, "wb")
        writer = png.Writer(w, h, greyscale=True, bitdepth=8)
        writer.write(preview_io, gray)
        preview_io.close()

        gcode_io = open(self.gcode_filename, "w")
        gcode_io.write(h_gcode.compile())

        if self.options.cross:
            if self.options.pause:
                gcode_io.write("M00\n")

            gcode_io.write(v_gcode.compile())
        
        gcode_io.close()

    def effect(self):
        try:
            self.check_dir()
            self.png_export()
            self.generate_gcode()
        except RuntimeError:
            return

if __name__ == "__main__":
    vo = VOLaserGCode()
    vo.affect()

    exit()
