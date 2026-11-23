"""knowledge.*: knowledge-base reads, remove/clear, and import/rebuild jobs with progress events."""
import sqlite3
import threading
from pathlib import Path
from PySide6.QtWidgets import QFileDialog

from ..assistant import RequestCancelled
from ..bridge import BridgeError


def handle(action, args, host):
    window = host.context['window']
    knowledge = window.knowledge
    if action == 'documents':
        return {'documents': list(knowledge.documents())}
    if action == 'stats':
        return knowledge.stats()
    if action == 'image':
        try:
            return knowledge.doc_image(str(args.get('imageId') or ''))
        except (OSError, ValueError) as exc:
            raise BridgeError(str(exc)) from None
    if action == 'search':
        query = str(args.get('query') or '').strip()
        if not query:
            raise BridgeError('query 不能为空')
        return {'hits': list(knowledge.search(query, preview=True))}
    if action == 'remove':
        doc_id = args.get('docId')
        if not isinstance(doc_id, str) or not doc_id:
            raise BridgeError('docId 不能为空')
        try:
            knowledge.remove(doc_id)
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise BridgeError(f'移除失败：{exc}') from None
        return {}
    if action == 'clear':
        try:
            knowledge.clear()
        except (OSError, ValueError, sqlite3.Error) as exc:
            raise BridgeError(f'清空失败：{exc}') from None
        return {}
    if action == 'assessments':
        return {'assessments': list(knowledge.assessments())}
    if action == 'assessment':
        assessment_id = str(args.get('assessmentId') or '')
        result = knowledge.assessment(assessment_id)
        if not result:
            raise BridgeError('测评模板不存在', code='NOT_FOUND')
        return result
    if action == 'assessmentImage':
        try:
            return knowledge.assessment_image(str(args.get('assessmentId') or ''),
                                              str(args.get('imageId') or ''))
        except (OSError, ValueError) as exc:
            raise BridgeError(str(exc)) from None
    if action == 'recognizeAssessmentImage':
        assessment_id = str(args.get('assessmentId') or '')
        image_id = str(args.get('imageId') or '')
        if not assessment_id or not image_id:
            raise BridgeError('assessmentId 和 imageId 不能为空')
        return _spawn_image_recognition(host, window, assessment_id, image_id)
    if action == 'assessmentImageFile':
        try:
            result = knowledge.assessment_image_file(str(args.get('assessmentId') or ''),
                                                     str(args.get('imageId') or ''))
            path, _ = QFileDialog.getSaveFileName(
                None, '导出题目图片', str(Path.home() / result['name']),
                f"图片文件 (*{Path(result['name']).suffix})")
            if not path:
                return {'file': None, 'cancelled': True}
            destination = Path(path)
            if destination.suffix.lower() != Path(result['name']).suffix.lower():
                destination = destination.with_suffix(Path(result['name']).suffix)
            destination.write_bytes(result['data'])
            return {'file': destination.name, 'cancelled': False}
        except (OSError, ValueError) as exc:
            raise BridgeError(str(exc)) from None
    if action == 'saveImageTranscription':
        try:
            return knowledge.save_image_transcription(
                str(args.get('assessmentId') or ''), str(args.get('imageId') or ''),
                str(args.get('questionId') or ''), args.get('transcription', ''), args.get('role'))
        except (OSError, ValueError) as exc:
            raise BridgeError(str(exc)) from None
    if action == 'saveAssessment':
        try:
            return knowledge.save_assessment(str(args.get('assessmentId') or ''),
                                             args.get('title', ''), args.get('questions'))
        except (OSError, ValueError) as exc:
            raise BridgeError(str(exc)) from None
    if action == 'deleteAssessment':
        knowledge.delete_assessment(str(args.get('assessmentId') or ''))
        return {}
    if action == 'gradeAssessment':
        answers = args.get('answers')
        if not isinstance(answers, dict) or not isinstance(args.get('assessmentId'), str):
            raise BridgeError('answers 必须是题目编号到答案的对象')
        return _spawn_grade(host, window, str(args.get('assessmentId') or ''), answers,
                            str(args.get('candidateName') or ''))
    if action == 'updateAssessmentRun':
        try:
            result = knowledge.update_assessment_run(str(args.get('runId') or ''), args.get('results'))
            return result
        except (OSError, ValueError) as exc:
            raise BridgeError(str(exc)) from None
    if action == 'deleteAssessmentRun':
        knowledge.delete_assessment_run(str(args.get('runId') or ''))
        return {}
    if action == 'exportAssessmentRun':
        return {'markdown': knowledge.export_assessment_run(str(args.get('runId') or ''))}
    if action == 'importAssessment':
        if getattr(window, '_bridge_kb_busy', False):
            raise BridgeError('已有知识库任务在进行，请等待完成或取消。', code='CONFLICT')
        path = str(args.get('path') or '')
        try:
            assessment = knowledge.create_assessment_from_docx(path)
        except (OSError, ValueError) as exc:
            raise BridgeError(str(exc)) from None
        if not assessment['images']:
            return {'assessment': assessment, 'jobId': None, 'visionSkipped': False}
        if not window.settings.get('base_url') or not window.settings.get('model'):
            return {'assessment': assessment, 'jobId': None, 'visionSkipped': True}
        job_id = _spawn_assessment_image_recognition(host, window, assessment)
        return {'assessment': assessment, 'jobId': job_id, 'visionSkipped': False}
    if action == 'rebuild':
        doc_id = str(args.get('docId') or '')
        if not doc_id:
            raise BridgeError('请先选择要重建的资料')
        try:
            match = next((doc for doc in knowledge.documents()
                          if str(doc.get('doc_id')) == doc_id), None)
        except (OSError, ValueError, sqlite3.Error):
            match = None
        if not match:
            raise BridgeError('资料不存在', code='NOT_FOUND')
        path = Path(str(match.get('source_path') or ''))
        if not path.is_file():
            raise BridgeError('没有可重建的资料：原始文件已被移动或删除。')
        return _spawn_import(host, window, [str(path)], force=True)
    if action == 'importPaths':
        paths = args.get('paths')
        if not isinstance(paths, list) or not paths:
            raise BridgeError('paths 必须是非空数组')
        return _spawn_import(host, window, [str(p) for p in paths], force=False)
    raise BridgeError(f'未知方法: knowledge.{action}', code='NOT_FOUND')


def _spawn_import(host, window, paths, force):
    if getattr(window, '_bridge_kb_busy', False):
        raise BridgeError('已有导入任务在进行，请等待完成或取消。', code='CONFLICT')
    job_id, cancel_event = host.create_job()
    window._bridge_kb_busy = True
    settings = dict(window.settings)

    def progress(message):
        host.emit_event('knowledge.jobProgress', {'jobId': job_id, 'message': str(message)})

    def work():
        added = updated = skipped = failed = 0
        errors, cancelled = [], False
        try:
            for path in paths:
                if cancel_event.is_set():
                    cancelled = True
                    break
                try:
                    if Path(path).is_dir():
                        results = window.knowledge.add_folder(path, settings, progress,
                                                               cancel_event.is_set, force=force)
                    else:
                        results = [window.knowledge.add_file(path, settings, progress,
                                                              cancel_event.is_set, force=force)]
                except RequestCancelled:
                    cancelled = True
                    break
                except (OSError, ValueError) as exc:
                    failed += 1
                    if len(errors) < 3:
                        errors.append(f'{Path(path).name}：{exc}')
                    continue
                for item in results:
                    status = item.get('status')
                    if status == 'added':
                        added += 1
                    elif status == 'updated':
                        updated += 1
                    elif status == 'skipped':
                        skipped += 1
                    else:
                        failed += 1
                    if item.get('error') and len(errors) < 3:
                        errors.append(f'{item.get("name")}：{item["error"]}')
                    elif item.get('wiki_error') and len(errors) < 3:
                        errors.append(f'{item.get("name")}：Wiki 未生成（{item["wiki_error"]}）')
        finally:
            window._bridge_kb_busy = False
            host.finish_job(job_id)
        host.emit_event('knowledge.jobDone', {
            'jobId': job_id, 'cancelled': cancelled, 'added': added, 'updated': updated,
            'skipped': skipped, 'failed': failed,
            'message': ('导入已取消：' if cancelled else '导入完成：')
                       + f'新增 {added}，更新 {updated}，跳过 {skipped}，失败 {failed}。'
                       + (' ' + '；'.join(errors) if errors else ''),
        })

    threading.Thread(target=work, daemon=True).start()
    return {'jobId': job_id}


def _spawn_grade(host, window, assessment_id, answers, candidate_name=''):
    if getattr(window, '_bridge_kb_busy', False):
        raise BridgeError('已有知识库任务在进行，请等待完成或取消。', code='CONFLICT')
    job_id, cancel_event = host.create_job()
    window._bridge_kb_busy = True
    settings = dict(window.settings)

    def progress(message):
        host.emit_event('knowledge.jobProgress', {'jobId': job_id, 'message': str(message)})

    def work():
        try:
            run = window.knowledge.grade_assessment(assessment_id, answers, settings,
                                                    progress, cancel_event.is_set, candidate_name)
            host.emit_event('knowledge.gradeDone', {'jobId': job_id, 'ok': True,
                                                    'run': run, 'message': '评分建议已生成，请逐题复核。'})
        except RequestCancelled:
            host.emit_event('knowledge.gradeDone', {'jobId': job_id, 'ok': False,
                                                    'cancelled': True, 'message': '评分已取消。'})
        except (OSError, ValueError) as exc:
            host.emit_event('knowledge.gradeDone', {'jobId': job_id, 'ok': False,
                                                    'cancelled': False, 'message': str(exc)})
        finally:
            window._bridge_kb_busy = False
            host.finish_job(job_id)

    threading.Thread(target=work, daemon=True).start()
    return {'jobId': job_id}


def _spawn_image_recognition(host, window, assessment_id, image_id):
    if getattr(window, '_bridge_kb_busy', False):
        raise BridgeError('已有知识库任务在进行，请等待完成或取消。', code='CONFLICT')
    job_id, cancel_event = host.create_job()
    window._bridge_kb_busy = True
    settings = dict(window.settings)

    def work():
        try:
            host.emit_event('knowledge.jobProgress', {
                'jobId': job_id, 'message': '正在将图片发送给当前配置的模型识别…',
            })
            text = window.knowledge.recognize_assessment_image(
                assessment_id, image_id, settings, cancel_event.is_set)
            host.emit_event('knowledge.visionDone', {
                'jobId': job_id, 'ok': True, 'assessmentId': assessment_id,
                'imageId': image_id, 'text': text, 'message': '图片识别完成，请校对结果后保存。',
            })
        except RequestCancelled:
            host.emit_event('knowledge.visionDone', {
                'jobId': job_id, 'ok': False, 'cancelled': True,
                'message': '图片识别已取消。',
            })
        except (OSError, ValueError) as exc:
            host.emit_event('knowledge.visionDone', {
                'jobId': job_id, 'ok': False, 'cancelled': False,
                'message': str(exc),
            })
        finally:
            window._bridge_kb_busy = False
            host.finish_job(job_id)

    threading.Thread(target=work, daemon=True).start()
    return {'jobId': job_id}


def _spawn_assessment_image_recognition(host, window, assessment):
    if getattr(window, '_bridge_kb_busy', False):
        raise BridgeError('已有知识库任务在进行，请等待完成或取消。', code='CONFLICT')
    job_id, cancel_event = host.create_job()
    window._bridge_kb_busy = True
    settings = dict(window.settings)
    images = list(assessment.get('images') or [])
    assessment_id = assessment['id']

    def work():
        completed = 0
        failed = []
        cancelled = False
        try:
            for index, image in enumerate(images, 1):
                if cancel_event.is_set():
                    cancelled = True
                    break
                host.emit_event('knowledge.jobProgress', {
                    'jobId': job_id,
                    'message': f'正在识别并关联第 {index}/{len(images)} 张图片：{image["name"]}',
                })
                try:
                    text = window.knowledge.recognize_assessment_image(
                        assessment_id, image['id'], settings, cancel_event.is_set)
                    window.knowledge.save_image_transcription(
                        assessment_id, image['id'], image.get('question_id') or '',
                        text, image.get('role') or 'unclassified')
                    completed += 1
                except RequestCancelled:
                    cancelled = True
                    break
                except (OSError, ValueError) as exc:
                    failed.append({'imageId': image['id'], 'name': image['name'], 'error': str(exc)})
                    # An unsupported vision model will reject every image. Stop the
                    # batch after the first unsupported response and leave the rest editable.
                    if '不支持图片输入' in str(exc):
                        failed.extend({'imageId': rest['id'], 'name': rest['name'],
                                       'error': '当前模型不支持图片输入，未继续识别。'}
                                      for rest in images[index:])
                        break
                except Exception:
                    failed.append({'imageId': image['id'], 'name': image['name'],
                                   'error': '图片识别或本地保存失败。'})
        finally:
            window._bridge_kb_busy = False
            host.finish_job(job_id)
        host.emit_event('knowledge.assessmentImportDone', {
            'jobId': job_id, 'assessmentId': assessment_id, 'completed': completed,
            'failed': failed, 'cancelled': cancelled,
            'message': ('图片识别已取消，已完成的转录已保存。' if cancelled else
                        f'图片识别完成：成功 {completed} 张，失败 {len(failed)} 张。'
                        + ('失败图片：' + '、'.join(item['name'] for item in failed[:5])
                           + ('…' if len(failed) > 5 else '') if failed else '') if failed else
                        f'图片识别完成：已转录并关联 {completed} 张图片。'),
        })

    threading.Thread(target=work, daemon=True).start()
    return job_id
