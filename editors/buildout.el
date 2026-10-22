;;; buildout.el --- Ask the Buildout engine from Emacs  -*- lexical-binding: t; -*-

;; Research only: nothing here can place an order.
;;
;; Install: put this file on your load-path, then
;;   (require 'buildout)
;;   (setq buildout-root "~/code/buildout")       ; the repository folder
;;   (global-buildout-mode 1)                     ; C-c b prefix everywhere
;;
;; Commands (M-x, or the C-c b keys):
;;   buildout-think     C-c b t   the mind's verdict on a question (the region, if active)
;;   buildout-what-if   C-c b w   a what-if over the belief network ("oil spikes, what happens to the book")
;;   buildout-triage    C-c b q   a quant's backtest Sharpe after costs, decay, luck and too little data
;;   buildout-erp       C-c b e   Damodaran's implied equity risk premium
;;   buildout-dcf       C-c b d   Damodaran's narrative DCF
;;   buildout-ml        C-c b m   rebuild the ML lab (network)
;;   buildout-reality   C-c b r   rebuild the reality check (network)

;;; Code:

(defgroup buildout nil "The Buildout research engine." :group 'tools)
(defcustom buildout-python "python3" "Interpreter that has the buildout package." :type 'string)
(defcustom buildout-root (file-name-directory (directory-file-name (file-name-directory (or load-file-name buffer-file-name default-directory))))
  "The Buildout repository folder." :type 'directory)

(defvar buildout-history nil "Questions asked.")

(define-derived-mode buildout-result-mode special-mode "Buildout"
  "Results from the Buildout engine."
  (setq-local font-lock-defaults
              '((("^\\s-*\\+ .*" . 'success) ("^\\s-*- .*" . 'error)
                 ("^\\s-*\\(hinge\\|chain\\|decision\\|what-if\\):" . 'font-lock-keyword-face)))))

(defun buildout--run (&rest args)
  "Run python -m buildout ARGS in `buildout-root' and show the output."
  (let ((default-directory (file-name-as-directory (expand-file-name buildout-root)))
        (buf (get-buffer-create "*buildout*")))
    (with-current-buffer buf
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (format "buildout %s\n\n" (mapconcat #'identity args " ")))
        (apply #'call-process buildout-python nil t nil "-m" "buildout" args))
      (buildout-result-mode)
      (goto-char (point-min)))
    (display-buffer buf)))

(defun buildout--ask (prompt)
  (if (use-region-p)
      (buffer-substring-no-properties (region-beginning) (region-end))
    (read-string prompt nil 'buildout-history)))

;;;###autoload
(defun buildout-think (question)
  "Ask the mind QUESTION."
  (interactive (list (buildout--ask "Ask the mind: ")))
  (buildout--run "think" question))

;;;###autoload
(defun buildout-what-if (condition)
  "Set CONDITION in the belief network and see what re-settles."
  (interactive (list (buildout--ask "What if: ")))
  (buildout--run "think" (concat "What if " condition)))

;;;###autoload
(defun buildout-triage (sharpe years trials)
  "Triage a backtest: SHARPE over YEARS after TRIALS variants."
  (interactive "nBacktest Sharpe: \nnYears: \nnVariants tried: ")
  (buildout--run "triage" (number-to-string sharpe) (number-to-string years) (number-to-string trials)))

;;;###autoload
(defun buildout-erp (cash-yield growth rf)
  "Damodaran's implied ERP from CASH-YIELD, GROWTH and RF (fractions)."
  (interactive "nCash yield (0.035): \nnGrowth (0.06): \nnRisk-free (0.0513): ")
  (buildout--run "erp" "--cash-yield" (number-to-string cash-yield) "--growth" (number-to-string growth) "--rf" (number-to-string rf)))

;;;###autoload
(defun buildout-dcf (revenue growth margin target)
  "Damodaran's narrative DCF from REVENUE, GROWTH, MARGIN now and TARGET margin."
  (interactive "nRevenue: \nnHigh growth (0.25): \nnMargin now (0.30): \nnTarget margin (0.35): ")
  (buildout--run "dcf" "--revenue" (number-to-string revenue) "--growth" (number-to-string growth)
                 "--margin" (number-to-string margin) "--target" (number-to-string target)))

;;;###autoload
(defun buildout-ml () "Rebuild the ML lab." (interactive) (buildout--run "ml" "--out" "site/data"))
;;;###autoload
(defun buildout-reality () "Rebuild the reality check." (interactive) (buildout--run "reality" "--out" "site/data"))

(defvar buildout-command-map
  (let ((m (make-sparse-keymap)))
    (define-key m "t" #'buildout-think)
    (define-key m "w" #'buildout-what-if)
    (define-key m "q" #'buildout-triage)
    (define-key m "e" #'buildout-erp)
    (define-key m "d" #'buildout-dcf)
    (define-key m "m" #'buildout-ml)
    (define-key m "r" #'buildout-reality)
    m)
  "Keys under the Buildout prefix.")

(defvar buildout-mode-map
  (let ((m (make-sparse-keymap))) (define-key m (kbd "C-c b") buildout-command-map) m))

;;;###autoload
(define-minor-mode buildout-mode "C-c b runs the Buildout engine." :lighter " Bo" :keymap buildout-mode-map)
;;;###autoload
(define-globalized-minor-mode global-buildout-mode buildout-mode (lambda () (buildout-mode 1)))

(provide 'buildout)
;;; buildout.el ends here
