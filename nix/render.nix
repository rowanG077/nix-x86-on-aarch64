lib: path: bindings:
lib.replaceStrings (map (name: "@${name}@") (builtins.attrNames bindings)) (map toString (
  builtins.attrValues bindings
)) (builtins.readFile path)
