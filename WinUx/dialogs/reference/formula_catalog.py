"""Formula palette metadata shared by the Reference Chart editor."""

FORMULA_FUNCTIONS = [
    ('regex', 'regex(".*U3.*")', 'Select History Outputs by a Python regular expression.'),
    ('combine', 'combine(regex(".*U3.*"), regex(".*RF3.*"))', 'Use U as X and RF as Y.'),
    ('signed_combine', 'combine(regex(".*U3.*"), -regex(".*RF3.*"))', 'Use U as X and negative RF as Y.'),
    ('plus', 'regex(".*U3.*") + 10', 'Add a constant; spaces are optional.'),
    ('minus', 'regex(".*RF3.*") - regex(".*U3.*")', 'Subtract series values.'),
    ('times', '0.5*regex(".*RF3.*")', 'Scale by a number; use 0.5 for 50 percent.'),
    ('quotient', 'regex(".*RF3.*")/1000', 'Convert force units.'),
    ('power', 'regex(".*U3.*")**2', 'Power, with Python/Abaqus precedence.'),
    ('remainder', 'regex(".*U3.*")%2', 'Remainder, not percentage.'),
    ('abs', 'abs(regex(".*RF3.*"))', 'Absolute value.'),
    ('sqrt', 'sqrt(regex(".*U3.*"))', 'Square root.'),
    ('sin', 'sin(regex(".*U3.*"))', 'Sine, radians.'),
    ('log', 'log(regex(".*U3.*"))', 'Natural logarithm, as in Abaqus.'),
    ('log10', 'log10(regex(".*U3.*"))', 'Base-10 logarithm.'),
    ('average', 'average(regex(".*U3.*"), regex(".*RF3.*"))', 'Sample-wise mean.'),
    *[(name, '{}(regex(".*U3.*"))'.format(name), description) for name, description in (
        ('cos', 'Cosine, radians.'), ('tan', 'Tangent, radians.'),
        ('asin', 'Inverse sine, radians.'), ('acos', 'Inverse cosine, radians.'),
        ('atan', 'Inverse tangent, radians.'), ('sinh', 'Hyperbolic sine.'),
        ('cosh', 'Hyperbolic cosine.'), ('tanh', 'Hyperbolic tangent.'),
        ('exp', 'Exponential.'), ('square', 'Square the value.'),
        ('negate', 'Reverse the sign.'), ('ln', 'Natural logarithm alias.'))],
    ('magnitude', 'magnitude(regex(".*U1.*"), regex(".*U2.*"), regex(".*U3.*"))', 'Vector magnitude.'),
    *[(name, '{}(regex(".*U3.*"), regex(".*RF3.*"))'.format(name), description)
      for name, description in (('add', 'Add series.'), ('subtract', 'Subtract series.'),
                                ('multiply', 'Multiply series.'), ('divide', 'Divide series.'))],
    ('scale', 'scale(regex(".*U3.*"), 2)', 'Multiply by a factor.'),
    ('offset', 'offset(regex(".*U3.*"), 10)', 'Add an offset.'),
]

FORMULA_LABELS = {
    'regex': 'regex("pattern")', 'combine': 'combine(X, Y)', 'signed_combine': 'combine(X, -Y)',
    'plus': 'A + B', 'minus': 'A - B', 'times': 'A * B', 'quotient': 'A / B',
    'power': 'A ** B', 'remainder': 'A % B',
    **{name: '{}(A, B, ...)'.format(name) for name in ('average', 'magnitude')},
    **{name: '{}(A, B)'.format(name) for name in ('add', 'subtract', 'multiply', 'divide')},
    'scale': 'scale(A, factor)', 'offset': 'offset(A, value)',
}

FORMULA_INSERTIONS = {
    **{name: name + '(' for name, _, _ in FORMULA_FUNCTIONS},
    'regex': 'regex("pattern")',
    'signed_combine': 'combine(',
    'plus': ' + ', 'minus': ' - ', 'times': ' * ', 'quotient': ' / ',
    'power': ' ** ', 'remainder': ' % ',
}

DEFAULT_FORMULA = 'combine(regex(".*U3.*"), -regex(".*RF3.*"))'

__all__ = ["FORMULA_FUNCTIONS", "FORMULA_LABELS", "FORMULA_INSERTIONS", "DEFAULT_FORMULA"]
