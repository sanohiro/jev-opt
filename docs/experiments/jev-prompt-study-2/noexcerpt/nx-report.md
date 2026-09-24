
**hintbench, phase A (functions)**

| variant | P(best) k2 | argmax hits | harm mass | harm argmax | KEEP argmax @KEEP | P(KEEP) @KEEP | named-FP mass | missing |
|---|---|---|---|---|---|---|---|---|
| L13 | 0.62 [0.55, 0.67] | 7 [7, 7]/8 | 0.04 [0.04, 0.04] | 0 [0, 0]/2 | 6 [6, 6]/7 | 0.84 [0.84, 0.85] | 0.04 [0.04, 0.05] | 0 |

**hintbench, phase B (loops)**

| variant | P(best) k3 loop | P(best) k5 loop | P(best) k8 loop | argmax hits | harm mass | harm argmax | KEEP argmax @KEEP | P(KEEP) @KEEP | named-FP mass | missing |
|---|---|---|---|---|---|---|---|---|---|---|
| L13 | 0.19 [0.15, 0.20] | 0.00 [0.00, 0.00] | 0.00 [0.00, 0.00] | 0 [0, 0]/4 | 0.16 [0.15, 0.17] | 1 [1, 1]/4 | 0 [0, 0]/1 | 0.40 [0.37, 0.42] | 0.53 [0.50, 0.54] | 0 |

**zopfli, phase A (functions)**

| variant | argmax hits | harm mass | harm argmax | KEEP argmax @KEEP | P(KEEP) @KEEP | named-FP mass | missing |
|---|---|---|---|---|---|---|---|
| L13 | 3 [3, 3]/6 | 0.25 [0.25, 0.25] | 1 [1, 1]/4 | 3 [3, 3]/6 | 0.50 [0.48, 0.50] | 0.99 [0.99, 1.00] | 0 |

**zopfli, phase B (loops)**

| variant | P(best) squeeze.rs:325 | argmax hits | harm mass | harm argmax | KEEP argmax @KEEP | P(KEEP) @KEEP | named-FP mass | missing |
|---|---|---|---|---|---|---|---|---|
| L13 | 0.00 [0.00, 0.00] | 4 [4, 4]/5 | 0.23 [0.23, 0.23] | 0 [0, 0]/2 | 4 [4, 4]/4 | 0.57 [0.56, 0.57] | 0.15 [0.15, 0.16] | 0 |
