# Shell setup for scripts/demo.tape (vhs can't type CJK, so the order command is preloaded into history).
export PS1='\[\e[38;2;217;119;87m\]❯\[\e[0m\] '
export HISTIGNORE='mcd --demo:clear:source*'
history -c
history -s 'mcd --demo order 巨无霸 中杯拿铁 薯条 麦乐鸡'
clear
