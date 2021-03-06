# Copyright (C) 2021 and later: Unicode, Inc. and others.
# License & terms of use: http://www.unicode.org/copyright.html
# Lint as: python3

import sys, getopt, json, struct

"""
Tool to convert Models/*/weights.json files into a resource file could be build
into ICU. The result should be copy to icu/icu4c/source/data/brkitr/lstm.
See https://docs.google.com/document/d/1EVK2CwOmUamJwMOMbbdTz7tuaV0IR21rMoH7a3pyFwE/edit#heading=h.qkedw6o6vy20
for detail design.
"""

def main(argv):
   inputfile = ''
   try:
     opts, args = getopt.getopt(argv,"hio::",["ifile=","ofile="])
   except getopt.GetoptError:
     print('convert_lstm_model.py -i <inputfile> -o <outputfile>')
     sys.exit(2)
   for opt, arg in opts:
      if opt == '-h':
        print('convert_lstm_model.py -i <inputfile> -o <outputfile>')
        sys.exit()
      elif opt in ("-i", "--ifile"):
        inputfile = arg
      elif opt in ("-o", "--ofile"):
        outfile = arg

   input = json.load(open(inputfile, 'r'))
   embeddings = input["mat1"]["dim"][1];
   hunits = input["mat3"]["dim"][0];
   dict_size = len(input["dic"])
   model = input["model"]
   type = ""
   if str.find(model, "_codepoints_") > 0:
     type = "codepoints"
   elif str.find(model, "_graphclust_") > 0:
     type = "graphclust"

   if type == "":
     print("Unknon type specified in the model. Need to be either 'codepoints' or 'graphclust'")
     sys.exit(2)

   verify_dimension(input, dict_size, embeddings, hunits)

   copyright="""\uFEFF// © 2021 and later: Unicode, Inc. and others.
// License & terms of use: http://www.unicode.org/copyright.html"""
   with open(outfile, 'w', encoding='utf-8') as f:
     print(copyright, file=f)
     print("{model}:table(nofallback){{".format(model=model), file=f)
     print("    model{{\"{model}\"}}".format(model=model), file=f)
     print("    type{{\"{type}\"}}".format(type=type), file=f)
     print("    embeddings:int{{{embeddings}}}".format(embeddings=embeddings), file=f)
     print("    hunits:int{{{hunits}}}".format(hunits=hunits), file=f)
     print_dict(input["dic"], file=f)
     print("    data:intvector{", file=f)
     print_float_in_int(input["mat1"]["data"], file=f)
     print_float_in_int(input["mat2"]["data"], file=f)
     print_float_in_int(input["mat3"]["data"], file=f)
     print_float_in_int(input["mat4"]["data"], file=f)
     print_float_in_int(input["mat5"]["data"], file=f)
     print_float_in_int(input["mat6"]["data"], file=f)
     print_float_in_int(input["mat7"]["data"], file=f)
     print_float_in_int(input["mat8"]["data"], file=f)
     print_float_in_int(input["mat9"]["data"], file=f)
     print("    }", file=f)
     print("}", file=f)

def print_dict(dict, file):
   print("    dict{", file=file)
   i = 0
   for k in dict:
     print("        \"{key}\",".format(key=k.replace('"', '\\"')), file=file)
     if i != dict[k]:
       print("Incorrect value for dic \"{k}\": {v}- expecting {i}"
             .format(k=k, v=dict[k], i=i))
       sys.exit(2)
     i += 1
   print("    }", file=file)

def print_float_in_int(data, file):
   # TODO currently we print each float as 32 bit int. We may later change it to
   # print two float as float16 into one 32 bit int.
   for i in data:
     print("        {f},".format(f=struct.unpack("i", struct.pack("f", i))[0]), file=file)

def verify_dimension(input, dict_size, embeddings, hunits):
   hunits4 = 4 * hunits
   hunits2 = 2 * hunits
   if (input["mat1"]["dim"][0] != dict_size + 1):
     dimension_error("mat1", dict_size + 1, input["mat1"]["dim"])
   if (input["mat1"]["dim"][1] != embeddings):
     dimension_error("mat1", embeddings, input["mat1"]["dim"])
   if (input["mat2"]["dim"][0] != embeddings):
     dimension_error("mat2", embeddings, input["mat2"]["dim"])
   if (input["mat2"]["dim"][1] != hunits4):
     dimension_error("mat2", hunits4, input["mat2"]["dim"])
   if (input["mat3"]["dim"][0] != hunits):
     dimension_error("mat3", hunits, input["mat3"]["dim"])
   if (input["mat3"]["dim"][1] != hunits4):
     dimension_error("mat3", hunits4, input["mat3"]["dim"])
   if (input["mat4"]["dim"][0] != hunits4):
     dimension_error("mat4", hunits4, input["mat4"]["dim"])
   if (input["mat5"]["dim"][0] != embeddings):
     dimension_error("mat5", embeddings, input["mat5"]["dim"])
   if (input["mat5"]["dim"][1] != hunits4):
     dimension_error("mat5", hunits4, input["mat5"]["dim"])
   if (input["mat6"]["dim"][0] != hunits):
     dimension_error("mat6", hunits, input["mat6"]["dim"])
   if (input["mat6"]["dim"][1] != hunits4):
     dimension_error("mat6", hunits4, input["mat6"]["dim"])
   if (input["mat7"]["dim"][0] != hunits4):
     dimension_error("mat7", hunits4, input["mat7"]["dim"])
   if (input["mat8"]["dim"][0] != hunits2):
     dimension_error("mat8", hunits2, input["mat8"]["dim"])
   if (input["mat8"]["dim"][1] != 4):
     dimension_error("mat8", 4, input["mat8"]["dim"])
   if (input["mat9"]["dim"][0] != 4):
     dimension_error("mat9", 4, input["mat9"]["dim"])

def dimension_error(name, value, dim):
   print("Dimension mismatch for {name}, expected {value}, but got {dim}"
         .format(name=name, value=value, dim=dim))
   sys.exit(2)

if __name__ == "__main__":
    main(sys.argv[1:])
